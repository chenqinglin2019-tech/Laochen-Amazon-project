"""r6 (report-always-v1): the run always ends with a report.

Run B0GFNWR8FW (2026-10-15, eyeliner stamp pen) reviewed every candidate in both chains - both rated USD959051S1 高 -
and still published nothing: a 低 row cited the patent's own Google page and drawing, which no binding list counted;
the retry re-sent the same prompt; there was no fallback. Each product the owner ran stopped at least once in the final
review for a different rule. These tests pin the r6 answers: one evidence set per candidate, row-level repair instead of
module refusal, pending rows for a module that cannot be obtained, a program-written chain summary, feedback retries,
a slimmer packet, the owner's invention-rating rule, and a pipeline that degrades instead of stopping.
"""
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest import mock

import decision_workflow as dw
import report_always


def _task():
    scenarios = dw.default_assessment_scenarios()
    for scenario in scenarios:
        scenario['scenario_sha256'] = dw.scenario_sha256(scenario)
    return {'task_id': 'IPRF-r6test', 'decision_workflow_revision': 'scenario-triage-v1', 'assessment_scenarios': scenarios,
            'primary_scenario_id': 'product_entry', 'target_jurisdictions': ['US'],
            report_always.TASK_FIELD: report_always.REVISION, 'screening_revision': 'recall-integrity-v1'}


def _packet(module='technical', index=None):
    import module_review as mr
    from assessment_estimate import required_product_scopes
    task = _task()
    rights = sorted(mr.GROUPS[module])
    return {'task': task, 'evidence_digest': 'd' * 64,
            'module_scope': {'revision': mr.REVISION, 'module_id': module, 'right_types': rights,
                             'required_scopes': required_product_scopes(task, set(rights)), 'global_input_digest': 'd' * 64},
            'candidate_evidence': index if index is not None else {
                'CAND-a': {'jurisdiction': 'US', 'right_type': 'patent', 'publication_number': 'US8894311B2',
                           'title': 'Eyeliner applicator',
                           'evidence': [{'ref': 'EV-page', 'role': 'document', 'label': '留存公开文本'},
                                        {'ref': 'EV-detail', 'role': 'detail_record', 'label': '准确详情记录（权利要求、状态）'},
                                        {'ref': 'EV-search', 'role': 'discovery', 'label': '检索结果卡片'}]}}}


def _row(task, **fields):
    scenario = task['assessment_scenarios'][0]
    row = {'scenario_id': 'product_entry', 'scenario_sha256': scenario['scenario_sha256'], 'jurisdiction': 'US',
           'right_type': 'patent', 'module_id': 'utility_patent', 'title': 'US8894311B2', 'scope': '入选候选',
           'risk': '低', 'assessment_status': 'assessed', 'reasoning': '独立项要求柔性细颈，产品没有。',
           'confidence_reasoning': '图片可见。', 'evidence_confidence': '中', 'evidence_refs': ['EV-page', 'IMG-001'],
           'supporting_evidence': [], 'counter_evidence': [{'reasoning': '没有柔性细颈。', 'evidence_refs': ['EV-page', 'IMG-001']}],
           'no_supporting_evidence_reasoning': '无。', 'no_counter_evidence_reasoning': '',
           'assumptions': [], 'raise_if': [], 'lower_if': [], 'human_checks': [], 'right_state': 'unknown',
           'confidence_basis': {}, 'candidate_id': 'CAND-a', 'assessment_object': 'product',
           'comparison': {'criteria': [{'criterion': 'independent_claim_1', 'result': 'excludes_risk',
                                        'reasoning': '缺少柔性细颈。', 'evidence_refs': ['EV-page']}]}}
    row.update(fields)
    return row


def _scope_rows(task, rights=('patent', 'utility_model')):
    scenario = task['assessment_scenarios'][0]
    return [{'scenario_id': 'product_entry', 'scenario_sha256': scenario['scenario_sha256'], 'jurisdiction': 'US',
             'right_type': right, 'module_id': 'utility_patent', 'title': 'US %s 整体' % right, 'scope': '整体',
             'risk': '低', 'assessment_status': 'assessed', 'reasoning': '有界检索后未发现具体威胁。',
             'confidence_reasoning': '有界检索。', 'evidence_confidence': '低', 'evidence_refs': ['EV-search'],
             'supporting_evidence': [], 'counter_evidence': [], 'no_supporting_evidence_reasoning': '无。',
             'no_counter_evidence_reasoning': '无。', 'assumptions': [], 'raise_if': [], 'lower_if': [],
             'human_checks': [], 'right_state': 'unknown', 'confidence_basis': {}, 'assessment_object': 'product'}
            for right in rights]


class CandidateEvidenceTests(unittest.TestCase):
    def _registry(self):
        return {
            'EV-search': {'evidence_id': 'EV-search', 'provider': 'serpapi_google_patents', 'operation': 'search',
                          'jurisdiction': 'US', 'right_type': 'patent', 'source_run_id': 'R1', 'query_id': 'Q1',
                          'plan_entry_sha256': 'p', 'requirement_ids': [], 'payload': {'candidates': [{'x': 1}]}},
            'EV-page': {'evidence_id': 'EV-page', 'provider': 'public_source', 'operation': 'retained_document',
                        'jurisdiction': 'US', 'right_type': 'patent', 'source_run_id': 'R2', 'query_id': 'Q2',
                        'kind': 'patent_document', 'path': '/x/page.html', 'sha256': 'a' * 64,
                        'source_url': 'https://patents.google.com/patent/US8894311B2/en',
                        'publication_number': 'US8894311B2', 'payload': {'candidate_id': 'CAND-a', 'kind': 'patent_document'}},
            'EV-drawing': {'evidence_id': 'EV-drawing', 'provider': 'public_source', 'operation': 'retained_document',
                           'jurisdiction': 'US', 'right_type': 'patent', 'source_run_id': 'R3', 'query_id': 'Q3',
                           'kind': 'patent_drawing_image', 'path': '/x/D00003.png', 'sha256': 'b' * 64,
                           'source_url': 'https://patentimages.storage.googleapis.com/x/US08894311-D00003.png',
                           'publication_number': 'US8894311B2', 'payload': {'candidate_id': 'CAND-a'}},
            'EV-failed': {'evidence_id': 'EV-failed', 'provider': 'public_source', 'operation': 'retained_document',
                          'jurisdiction': 'US', 'right_type': 'patent', 'source_run_id': 'R4', 'query_id': 'Q4',
                          'kind': 'patent_document', 'path': '/x/f.pdf', 'sha256': 'c' * 64,
                          'source_url': 'https://patentimages.storage.googleapis.com/f.pdf', 'payload': {'candidate_id': 'CAND-a'}},
            'EV-design': {'evidence_id': 'EV-design', 'provider': 'public_source', 'operation': 'retained_document',
                          'jurisdiction': 'US', 'right_type': 'design', 'source_run_id': 'R5', 'query_id': 'Q5',
                          'kind': 'design_document', 'path': '/x/d.pdf', 'sha256': 'd' * 64,
                          'source_url': 'https://image-ppubs.uspto.gov/d.pdf', 'payload': {'candidate_id': 'CAND-a'}},
        }

    def _evidence(self):
        runs = [{'run_id': 'R1', 'provider': 'serpapi_google_patents', 'operation': 'search', 'query_id': 'Q1',
                 'jurisdiction': 'US', 'right_type': 'patent', 'status': 'success', 'plan_entry_sha256': 'p',
                 'requirement_ids': []}]
        for run, query, status, right in (('R2', 'Q2', 'success', 'patent'), ('R3', 'Q3', 'success', 'patent'),
                                          ('R4', 'Q4', 'failed', 'patent'), ('R5', 'Q5', 'success', 'design')):
            runs.append({'run_id': run, 'provider': 'public_source', 'operation': 'retained_document', 'query_id': query,
                         'jurisdiction': 'US', 'right_type': right, 'status': status})
        return {'source_runs': runs, 'collections': {}}

    def test_the_candidates_own_page_and_drawing_count(self):
        import candidate_evidence
        candidates = {'patents': [{'candidate_id': 'CAND-a', 'publication_number': 'US8894311B2', 'right_type': 'patent',
                                   'jurisdiction': 'US', 'evidence_refs': ['EV-search']}]}
        with mock.patch('trusted_api.enabled', return_value=False):
            roles = candidate_evidence.evidence_roles(_task(), self._evidence(), candidates, self._registry(),
                                                      'CAND-a', 'US', 'patent')
        self.assertEqual(roles, {'EV-drawing': 'drawing', 'EV-page': 'document', 'EV-search': 'discovery'})

    def test_rating_binding_is_the_publication_rule(self):
        from candidate_evidence import rating_binding
        refs = {'CAND-a': ['EV-page', 'EV-detail']}
        task = _task()
        self.assertIsNone(rating_binding(_row(task), refs))
        # one counter argument citing the candidate is enough (publication moves the others aside)
        self.assertIsNone(rating_binding(_row(task, counter_evidence=[
            {'reasoning': 'a', 'evidence_refs': ['IMG-001']}, {'reasoning': 'b', 'evidence_refs': ['EV-page']}]), refs))
        self.assertEqual(rating_binding(_row(task, counter_evidence=[{'reasoning': 'a', 'evidence_refs': ['IMG-001']}]),
                                        refs), 'CANDIDATE_RATING_BINDING_REQUIRED')
        self.assertEqual(rating_binding(_row(task, comparison={}), refs), 'CANDIDATE_RATING_CRITERIA_REQUIRED')
        self.assertEqual(rating_binding(_row(task, risk='高', supporting_evidence=[
            {'reasoning': 'x', 'evidence_refs': ['IMG-001']}]), refs), 'CANDIDATE_RATING_BINDING_REQUIRED')
        self.assertIsNone(rating_binding(_row(task, risk='高', supporting_evidence=[
            {'reasoning': 'x', 'evidence_refs': ['EV-detail']}]), refs))


class RepairTests(unittest.TestCase):
    def _raw(self, rows=None):
        task = _task()
        return {'assessments': rows if rows is not None else [_row(task)] + _scope_rows(task),
                'future_applications': [], 'enforcement_signals': [],
                'final_review_statement': {'overall': '总体。', 'scope': '范围。', 'limitations': '限制。'}}

    def test_a_valid_answer_passes_unchanged_and_derive_is_pure(self):
        from module_repair import derive
        raw, packet = self._raw(), _packet()
        before = deepcopy(raw)
        first, record = derive(raw, packet)
        second, again = derive(raw, packet)
        self.assertEqual(raw, before)
        self.assertEqual((first, record), (second, again))
        self.assertEqual(record['demoted_units'], {})
        self.assertEqual(len(first['assessments']), 3)

    def test_program_owned_fields_are_filled(self):
        from module_repair import derive
        task = _task()
        row = _row(task, scenario_sha256='0' * 64, module_id='appearance_patent')
        row.pop('confidence_reasoning')
        judged, record = derive(self._raw([row] + _scope_rows(task)), _packet())
        fixed = judged['assessments'][0]
        self.assertEqual(fixed['scenario_sha256'], task['assessment_scenarios'][0]['scenario_sha256'])
        self.assertEqual(fixed['module_id'], 'utility_patent')
        self.assertTrue(fixed['confidence_reasoning'])
        self.assertIn('scenario_sha256_filled', record['repairs'])

    def test_the_eyeliner_row_binds_with_the_candidates_page(self):
        from module_repair import derive
        judged, record = derive(self._raw(), _packet())
        self.assertEqual(judged['assessments'][0]['risk'], '低')
        task = _task()
        unbound = _row(task, evidence_refs=['IMG-001'], counter_evidence=[{'reasoning': 'x', 'evidence_refs': ['IMG-001']}],
                       comparison={'criteria': [{'criterion': 'c', 'result': 'excludes_risk', 'reasoning': 'r',
                                                 'evidence_refs': ['IMG-001']}]})
        judged, record = derive(self._raw([unbound] + _scope_rows(task)), _packet())
        demoted = judged['assessments'][0]
        self.assertEqual((demoted['risk'], demoted['assessment_status']), (None, 'pending'))
        self.assertEqual(demoted['demoted_from']['risk'], '低')
        self.assertIn('CANDIDATE_RATING_BINDING_REQUIRED', record['demoted_units'].values())

    def test_foreign_and_unselected_rows_are_dropped_missing_units_added(self):
        from module_repair import derive
        task = _task()
        foreign = _row(task, right_type='design', module_id='appearance_patent', candidate_id='CAND-x')
        stranger = _row(task, candidate_id='CAND-not-selected')
        judged, record = derive(self._raw([foreign, stranger]), _packet())
        units = {(row['right_type'], row.get('candidate_id')) for row in judged['assessments']}
        self.assertEqual(units, {('patent', None), ('utility_model', None), ('patent', 'CAND-a')})
        self.assertTrue(all(row['assessment_status'] == 'pending' for row in judged['assessments']))
        self.assertEqual(len(record['added_units']), 3)

    def test_an_unbound_out_of_scope_row_becomes_pending(self):
        from module_repair import derive
        task = _task()
        rows = _scope_rows(task)
        rows[0] = {**rows[0], 'risk': None, 'out_of_scope': True, 'scope_reasoning': '用户说不用。',
                   'assessment_status': 'assessed'}
        judged, record = derive(self._raw([_row(task)] + rows), _packet())
        self.assertIn('OUT_OF_SCOPE_NOT_BOUND_TO_TASK', record['demoted_units'].values())

    def test_host_actions_only_remove_or_demote(self):
        from module_repair import derive
        from final_review import unit_id
        raw, packet = self._raw(), _packet()
        key = unit_id(raw['assessments'][0])
        judged, record = derive(raw, packet, {'drop_refs': {key: ['IMG-001']}, 'demote': {}})
        self.assertNotIn('IMG-001', judged['assessments'][0]['evidence_refs'])
        judged, record = derive(raw, packet, {'demote': {key: 'UNKNOWN_OR_INVALID_EVIDENCE_REFS'}})
        self.assertIsNone(judged['assessments'][0]['risk'])
        self.assertEqual(record['demoted_units'], {key: 'UNKNOWN_OR_INVALID_EVIDENCE_REFS'})

    def test_an_answer_without_assessments_is_refused_for_a_retry(self):
        from module_repair import derive
        from review_judgment import ModelJudgmentError
        with self.assertRaises(ModelJudgmentError):
            derive({'assessments': []}, _packet())

    def test_an_answer_that_only_reuses_earlier_units_is_complete(self):
        from module_repair import derive
        from final_review import unit_id
        task = _task()
        units = [unit_id(row) for row in [_row(task)] + _scope_rows(task)]
        packet = {**_packet(), 'review_reuse': {'reusable_unit_ids': units}}
        judged, record = derive({'assessments': [], 'reused_unit_ids': units}, packet)
        self.assertEqual((judged['assessments'], judged['reused_unit_ids'], record['added_units']), ([], units, []))

    def test_the_fallback_is_pending_everywhere(self):
        from module_repair import fallback_judgment
        judged = fallback_judgment(_packet(), 'REPORT_REVIEW_HOST_EXECUTION_FAILED')
        self.assertEqual(len(judged['assessments']), 3)
        self.assertTrue(all(row['risk'] is None and row['pending_basis'] == 'MODULE_UNAVAILABLE'
                            for row in judged['assessments']))
        self.assertEqual(judged, fallback_judgment(_packet(), 'REPORT_REVIEW_HOST_EXECUTION_FAILED'))

    def test_missing_reading_observations_are_registered_not_refused(self):
        from module_repair import derive
        packet = _packet()
        packet['retained_originals'] = {'revision': 'public-originals-v2',
                                        'materials': [{'material_id': 'M1', 'source_refs': ['EV-page']},
                                                      {'material_id': 'M2', 'source_refs': ['EV-drawing']}]}
        raw = self._raw()
        raw['material_observations'] = {'M1': {'observation': '权利要求1。', 'limitations': '无。'}}
        judged, record = derive(raw, packet)
        self.assertEqual(sorted(judged['material_observations']), ['M1', 'M2'])
        self.assertIn('observation_filled', record['repairs'])


class ReviewFlowTests(unittest.TestCase):
    def test_retry_feedback_keeps_the_slots_identity(self):
        import module_review as mr
        from review_judgment import ModelJudgmentError
        prompt = mr.feedback_prompt('BASE', ModelJudgmentError('REPORT_REVIEW_HOST_OUTPUT_INVALID'))
        self.assertTrue(prompt.startswith('BASE'))
        self.assertIn('不是可以解析的 JSON', prompt)
        self.assertTrue(mr.same_prompt(prompt, 'BASE'))
        self.assertFalse(mr.same_prompt('OTHER', 'BASE'))

    def test_the_program_summary_is_deterministic_and_names_fallbacks(self):
        import module_review as mr
        modules = [('technical', {'final_review_statement': {'overall': 'a', 'scope': 'b', 'limitations': 'c'}}),
                   ('appearance', {'final_review_statement': {'overall': 'd', 'scope': 'e', 'limitations': 'f'}})]
        one = mr.program_summary_judgment('1', modules, ['appearance'])
        self.assertEqual(one, mr.program_summary_judgment('1', modules, ['appearance']))
        self.assertIn('外观', one['final_review_statement']['limitations'])
        self.assertEqual(one['assessments'], [])
        record = mr.program_summary_record('1', one, 'd' * 64)
        self.assertTrue(record['session_id'].startswith('program-summary-1-'))
        self.assertEqual(record['synthetic'], mr.PROGRAM_SUMMARY_REVISION)

    def test_a_session_that_cannot_start_is_a_failed_turn_of_its_slot(self):
        import module_review as mr
        with mock.patch('report_review_host.run_native_logged', side_effect=ValueError('EXECUTION_TIME_BUDGET_EXHAUSTED')):
            jobs = [{'command': ['x'], 'prompt': 'p', 'workspace': '/tmp', 'trace_path': '/nonexistent/t',
                     'stderr_path': '/nonexistent/e'}]
            with mock.patch.object(mr, 'STAGGER_SECONDS', 0):
                outcome = mr.run_jobs(jobs, 10, 1, soft=True)[0]
        self.assertEqual(outcome[0].returncode, mr.UnstartedProcess.returncode)

    def test_the_packet_diet_keeps_the_selected_candidates(self):
        import module_review as mr
        packet = {'candidates': {'identity_relationships': {'relations': [
                      {'relation': 'suspected_duplicate', 'candidate_ids': ['CAND-a', 'CAND-b']},
                      {'relation': 'suspected_duplicate', 'candidate_ids': ['CAND-x', 'CAND-y']}]}},
                  'evidence': {'result_dispositions': [{'outcome': 'candidate'}, {'outcome': 'candidate'}]},
                  'materiality_ledger': {'annotations': [{'candidate_id': 'CAND-a', 'decision': 'selected'},
                                                         {'candidate_id': 'CAND-x', 'decision': 'not_selected'}]},
                  'task': {'candidate_triage_stage_events': [1, 2], 'discovery_followups': [1],
                           'product_scope': {'candidate_links': [{'candidate_id': 'CAND-a'}, {'candidate_id': 'CAND-x'}]}}}
        mr.r6_diet(packet, {'CAND-a', 'CAND-b'})
        self.assertEqual(len(packet['candidates']['identity_relationships']['relations']), 1)
        self.assertNotIn('result_dispositions', packet['evidence'])
        self.assertEqual([row['candidate_id'] for row in packet['materiality_ledger']['annotations']], ['CAND-a'])
        self.assertEqual(packet['triage_statistics']['result_dispositions']['total'], 2)
        self.assertNotIn('candidate_triage_stage_events', packet['task'])


class AdjudicationRuleTests(unittest.TestCase):
    def test_the_marking_must_name_this_patent(self):
        import prepare_adjudication as pa
        task = {'product': {'title': 'Eyeliner Stamp, patent pending',
                            'bullets': ['Protected by US Patent No. 10,966,503 B1', 'design D959,051']}}
        self.assertTrue(pa.marking_for(task, 'US10966503B1'))
        self.assertTrue(pa.marking_for(task, 'USD959051S1'))
        self.assertIsNone(pa.marking_for(task, 'US8894311B2'))
        self.assertIsNone(pa.marking_for({'product': {'title': 'patent pending'}}, 'US10966503B1'))

    def test_the_owners_invention_rule(self):
        import prepare_adjudication as pa
        def row(*results):
            return {'comparison': {'claims': [{'claim_type': 'independent',
                                               'elements': [{'result': result} for result in results]}]}}
        self.assertEqual(pa.utility_cap_level(row('supports_risk', 'supports_risk')), '极高')
        self.assertEqual(pa.utility_cap_level(row('supports_risk', 'unknown')), '中')
        self.assertEqual(pa.utility_cap_level(row('unknown', 'unknown')), '低')
        self.assertEqual(pa.utility_cap_level(row('supports_risk', 'excludes_risk')), '低')
        self.assertIsNone(pa.utility_cap_level({}))

    def test_a_single_usable_review_drafts_the_decision(self):
        import prepare_adjudication as pa
        task = _task()
        usable = _row(task)
        pending = {**_row(task), 'risk': None, 'assessment_status': 'pending', 'pending_basis': 'MODULE_UNAVAILABLE'}
        self.assertIs(pa._single_review(task, pending, usable), usable)
        self.assertIs(pa._single_review(task, usable, pending), usable)
        self.assertIsNone(pa._single_review(task, usable, deepcopy(usable)))
        self.assertIsNone(pa._single_review({}, pending, usable))


class PipelineTests(unittest.TestCase):
    def _pipeline(self, root):
        import run_pipeline
        (root / 'task.json').write_text(json.dumps(_task()), encoding='utf-8')
        args = run_pipeline.parser().parse_args(['--task-dir', str(root)])
        return run_pipeline.Pipeline(args)

    def test_a_failing_bookkeeping_step_is_retried_then_disclosed(self):
        import run_pipeline
        with tempfile.TemporaryDirectory() as folder:
            pipeline = self._pipeline(Path(folder))
            failed = mock.Mock(returncode=1, stdout='', stderr='MECHANICAL_LEDGER_SOMETHING_WRONG')
            with mock.patch('subprocess.run', return_value=failed) as run:
                code, _, _ = pipeline.call('sources', run_pipeline.py('mechanical_ledger.py', '--task-dir', folder))
            self.assertEqual((code, run.call_count), (1, 2))
            self.assertEqual(pipeline.state['degraded_steps'][0]['script'], 'mechanical_ledger.py')
            corrupt = mock.Mock(returncode=1, stdout='', stderr='EVIDENCE_HASH_MISMATCH')
            with mock.patch('subprocess.run', return_value=corrupt):
                with self.assertRaises(run_pipeline.StageFailed):
                    pipeline.call('sources', run_pipeline.py('mechanical_ledger.py', '--task-dir', folder))

    def test_an_unexpected_fault_ends_the_stage_cleanly(self):
        import run_pipeline
        with tempfile.TemporaryDirectory() as folder:
            pipeline = self._pipeline(Path(folder))
            with self.assertRaises(run_pipeline.StageFailed) as caught:
                pipeline.stage('core', lambda: {}['missing'])
            self.assertEqual(caught.exception.code, 'PIPELINE_UNEXPECTED_KEYERROR')
            self.assertEqual(pipeline.state['stages']['core']['status'], 'failed')

    def test_a_second_time_box_closure_keeps_the_first(self):
        import time_box
        with tempfile.TemporaryDirectory() as folder:
            task = {'task_id': 'T', 'time_box_revision': time_box.REVISION}
            time_box.close(folder, task, [{'work_id': 'W1', 'state': 'ready'}], active_seconds=1, why='time_box')
            data = time_box.close(folder, task, [{'work_id': 'W2', 'state': 'awaiting_review'}], active_seconds=2,
                                  why='round_closed', keep=['W1'])
            self.assertEqual(data['work_ids'], ['W1', 'W2'])


class PrecisionTests(unittest.TestCase):
    def test_schedule_a_words_for_new_tasks_only(self):
        import triage_defaults as td
        self.assertTrue(td._enforcement('Eyeliner stamp Schedule A defendants', {'r6': True}))
        self.assertFalse(td._enforcement('Eyeliner stamp Schedule A defendants', {'r6': False}))
        from api_first_planning import provider_params
        term = {'value': 'eyeliner stamp', 'kind': 'product'}
        query = provider_params('serper_web', term, 'US', 'enforcement', retrieval_revision='api-first-v3',
                                public_discovery_revision='public-discovery-v1', schedule_a=True)['q']
        self.assertIn('"Schedule A" OR TRO', query)
        old = provider_params('serper_web', term, 'US', 'enforcement', retrieval_revision='api-first-v3',
                              public_discovery_revision='public-discovery-v1')['q']
        self.assertNotIn('Schedule A', old)

    def test_a_long_claim_element_keeps_its_tail(self):
        import comparison_host as ch
        text = 'A device comprising: ' + ', '.join('a member number %d having a surface' % i for i in range(60)) + '; and a cap.'
        old = ch.split_elements(1, text)
        new = ch.split_elements(1, text, whole=True)
        self.assertTrue(all(len(item['quote']) <= ch.MAX_ELEMENT_CHARS for item in new))
        self.assertTrue(all(ch.quote_verified(item['quote'], text) for item in new))
        self.assertIn('number 59', ' '.join(item['quote'] for item in new))
        self.assertNotIn('number 59', ' '.join(item['quote'] for item in old))

    def test_the_screen_keeps_broader_claims_and_ranks_by_relevance(self):
        import recall_screen
        prompt = recall_screen.text_prompt({'precision': True, 'claims_breadth': True, 'product': {}, 'objects': [],
                                            'units': []})
        self.assertIn('不要只因为摘要还写了本产品没有的附加部件就不列出', prompt)
        self.assertNotIn('不要只因为', recall_screen.text_prompt({'precision': True, 'product': {}, 'objects': [], 'units': []}))
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, 'normalized-candidates.json').write_text(json.dumps({'patents': [
                {'candidate_id': 'C1', 'source_position': 7}, {'candidate_id': 'C2', 'source_position': 2,
                                                               'sources': [{'position': 1}]}]}), encoding='utf-8')
            self.assertEqual(recall_screen._source_ranks(folder), {'C1': 7, 'C2': 1})

    def test_new_tasks_carry_the_marker_and_the_review_rules(self):
        text = (Path(__file__).parent / 'create_task.py').read_text(encoding='utf-8')
        self.assertIn('task[REPORT_ALWAYS_FIELD] = REPORT_ALWAYS_REVISION', text)
        from report_review_host import R6_REVIEW_RULE, R6_UTILITY_RULE
        self.assertIn('candidate_evidence', R6_REVIEW_RULE)
        self.assertIn('一个都看不到→低', R6_UTILITY_RULE)

    def test_a_directory_made_beforehand_still_takes_the_new_task(self):
        # owner run B0GFNWR8FW-US-r6-2: the Agent made the directory first, run_pipeline logged its auth step there and
        # create_task refused the directory as not empty - no task, no report
        import subprocess
        import sys
        from offline_test_support import isolated_test_environment, offline_environment
        script = Path(__file__).parent / 'create_task.py'
        with isolated_test_environment(), tempfile.TemporaryDirectory() as folder:
            def create(run):
                return subprocess.run([sys.executable, str(script), '--url', 'https://www.amazon.com/dp/B0GFNWR8FW',
                                       '--jurisdictions', 'US', '--output-dir', str(run)],
                                      capture_output=True, text=True, env=offline_environment())
            run = Path(folder, 'B0GFNWR8FW-US-r6-2')
            run.mkdir()
            for name in ('pipeline-state.json', 'pipeline-log.jsonl', '.DS_Store', '._task.json'):
                (run / name).write_text('{}\n', encoding='utf-8')
            result = create(run)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            task = json.loads((run / 'task.json').read_text(encoding='utf-8'))
            self.assertEqual(task[report_always.TASK_FIELD], report_always.REVISION)
            self.assertEqual((run / 'pipeline-log.jsonl').read_text(encoding='utf-8'), '{}\n')
            used = Path(folder, 'used')
            used.mkdir()
            (used / 'evidence.json').write_text('{}', encoding='utf-8')
            refused = create(used)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn('must be empty', refused.stderr)
            self.assertFalse((used / 'task.json').exists())
            nested = Path(folder, 'nested')
            (nested / 'pipeline-log.jsonl').mkdir(parents=True)
            self.assertNotEqual(create(nested).returncode, 0)


if __name__ == '__main__':
    unittest.main()
