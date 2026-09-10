"""Offline report projection tests; fixtures never authenticate or call sources."""
from copy import deepcopy
import csv
import io
import json
import unittest
from unittest.mock import patch

import report_estimate as report
from report_query_trace import build_query_trace, ZERO_WARNING
import test_report_estimate as legacy_report_tests
from common import atomic_write_json, sha256_file, sha256_json


class PartialEvidenceReportTests(unittest.TestCase):
    def setUp(self):
        self.fixture = legacy_report_tests.EstimateReportTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        # At this pure renderer boundary, no account configuration is consulted.
        security = patch.object(report, '_security_errors', return_value=[])
        security.start()
        self.addCleanup(security.stop)
        self.task = self.fixture.task
        self.assessment = self.fixture.assessment
        self.evidence = self.fixture.evidence
        self.task.update(assessment_revision='partial-evidence-v1')
        self.assessment.update(status='incomplete', assessment_revision='partial-evidence-v1')
        self.assessment['overall'].update(risk='低', risk_basis='policy_fallback', business_completion='incomplete')
        self.row = self.assessment['assessments'][0]
        self.row.update(risk='低', risk_basis='policy_fallback', assessment_status='pending',
            aggregation_included=False, risk_aggregation_included=True)
        self.plan = {'queries': {'source': []}}
        self.candidates = {}

    def build(self):
        f = self.fixture
        return report.build_report_data(f.root, self.task, self.evidence, self.assessment,
            self.candidates, f.journal, self.plan, output_dir=f.out, verify_assessment=False,
            visual_policy_revision=None)

    def query(self, identifier='Q1', **changes):
        query = {'query_id': identifier, 'provider': 'source', 'jurisdiction': 'US',
            'right_type': 'design', 'q': 'planned broad words', 'required': True, **changes}
        self.plan['queries']['source'].append(query)
        return query

    def attempt(self, query, identifier='R1', status='success', total=1, retrieved=1, truncated=False, **changes):
        run = {'run_id': identifier, 'query_id': query['query_id'], 'provider': 'source',
            'jurisdiction': query['jurisdiction'], 'right_type': query['right_type'],
            'status': status, 'q': query['q'], 'checked_at': '2026-09-01T01:02:03Z',
            'submission_state': 'submitted', 'metadata': {'query_semantics': {'rendered_query': '"narrow exact phrase"'},
                'search_coverage': {'schema_valid': True, 'total_hits': total, 'retrieved_hits': retrieved,
                    'truncated': truncated, 'stop_reason': 'recorded_result_boundary'}},
            'plan_entry_sha256': sha256_json(query), **changes}
        self.evidence.setdefault('source_runs', []).append(run)
        self.evidence['collections'].append({'evidence_id': 'EV-' + identifier, 'source_run_id': identifier,
            'source_url': 'https://example.com/results?id=' + identifier, 'source_name': 'synthetic source',
            'source_checked_at': '2025-01-01T00:00:00Z', 'payload': {'candidates': []}})
        return run

    def rendered(self, data):
        return report.render_html(data, self.fixture.out), report.render_markdown(data), report.render_findings_csv(data)

    def bounded_discovery(self, *, hit=False):
        query = self.query(provider='serper_web', operation='search', action_purpose='discovery', requirement_ids=['REQ-DISCOVERY'])
        run = self.attempt(query, status='success' if hit else 'no_result', total=None, retrieved=None, truncated=None,
            provider='serper_web', operation='search', requirement_ids=['REQ-DISCOVERY'], metadata={})
        entry = self.evidence['collections'][-1]
        entry.update({key: run[key] for key in ('provider', 'query_id', 'operation', 'jurisdiction', 'right_type', 'requirement_ids', 'plan_entry_sha256')})
        raw_cards = [{'title': 'Bounded discovery card', 'link': 'https://example.com/card'}] if hit else []
        entry['payload']['candidates'] = [{**item, 'source_record_sha256': sha256_json(item)} for item in raw_cards]
        path = self.fixture.root / 'bounded-response.json'
        atomic_write_json(path, {'organic': raw_cards})
        run.update(raw_paths=[str(path)], payload_digest=sha256_file(path))
        self.evidence['collections'] = {'discovery': self.evidence['collections']}
        self.assessment['review'] = {'evidence_root': str(self.fixture.root)}
        return query, run, entry, path

    def test_zero_search_keeps_new_risk_and_pending_facts_in_all_formats(self):
        self.task['coverage_requirements'] = [{'requirement_id': 'REQ-WORD', 'jurisdiction': 'US', 'right_type': 'trademark_word', 'phase': 'official_recall'}]
        before = deepcopy((self.task, self.evidence, self.assessment, self.plan))
        data = self.build()
        self.assertEqual(before, (self.task, self.evidence, self.assessment, self.plan))
        self.assertEqual(data['overall']['risk'], '低')
        self.assertEqual(data['assessments'][0]['assessment_status'], 'pending')
        self.assertFalse(data['assessments'][0]['aggregation_included'])
        self.assertEqual(data['modules'][0]['risk'], '低')
        self.assertEqual(data['modules'][0]['risk_basis'], 'policy_fallback')
        self.assertEqual(data['query_trace']['summary']['unfinished_step_count'], 1)
        for content in self.rendered(data):
            self.assertIn(ZERO_WARNING, content)
            self.assertIn('规则兜底', content)
            self.assertNotIn('证据不足的项目尚未定级', content)
        rows = list(csv.DictReader(io.StringIO(report.render_findings_csv(data))))
        conclusion = next(item for item in rows if item['row_type'] == 'assessment')
        self.assertEqual((conclusion['risk'], conclusion['confidence']), ('低', '低'))
        self.assertEqual(conclusion['aggregation_included'], 'False')
        self.assertEqual(conclusion['risk_aggregation_included'], 'True')

    def test_source_valid_bounded_zero_is_effective_response_not_official_coverage(self):
        query, run, _, _ = self.bounded_discovery()
        self.assessment['coverage']['scopes'] = [{'jurisdiction': 'US', 'right_type': 'design',
            'verification_status': 'incomplete', 'gaps': ['OFFICIAL_COVERAGE_UNVERIFIED']}]
        for metadata in ({}, {'search_coverage': {'schema_valid': True, 'total_hits': None,
                'retrieved_hits': 0, 'truncated': True, 'stop_reason': 'bounded_discovery_total_unknown'}}):
            run['metadata'] = metadata
            with self.subTest(metadata=metadata):
                data = self.build()
                trace = data['query_trace']
                attempt = trace['queries'][0]['attempts'][0]
                self.assertEqual(attempt['status'], 'no_match')
                self.assertTrue(attempt['effective'])
                self.assertTrue(attempt['bounded_discovery'])
                self.assertTrue(attempt['response_complete'])
                self.assertFalse(attempt['coverage_complete'])
                self.assertIsNone(attempt['total_hits'])
                self.assertEqual(attempt['retrieved_hits'], 0)
                self.assertEqual(trace['summary']['effective_search_count'], 1)
                self.assertEqual(trace['summary']['unfinished_step_count'], 1)
                self.assertFalse(any(item.get('query_id') == query['query_id'] for item in trace['unfinished_work']))
                for content in self.rendered(data):
                    self.assertIn('已完成有界发现响应，官方覆盖仍未知', content)
                    self.assertIn('本次成功查询无命中', content)
                    self.assertNotIn('有效检索为零', content)

    def test_source_valid_bounded_hit_retains_cards_without_inventing_total(self):
        self.bounded_discovery(hit=True)
        data = self.build()
        attempt = data['query_trace']['queries'][0]['attempts'][0]
        self.assertEqual(attempt['status'], 'hit')
        self.assertTrue(attempt['effective'])
        self.assertFalse(attempt['coverage_complete'])
        self.assertEqual(attempt['retrieved_hits'], 1)
        self.assertIsNone(attempt['total_hits'])
        for content in self.rendered(data):
            self.assertIn('Bounded discovery card', content)

    def test_bounded_source_integrity_and_submission_failures_do_not_become_no_match(self):
        _, run, entry, path = self.bounded_discovery()
        saved = deepcopy(run)
        for field, value in [('payload_digest', '0' * 64), ('submission_state', 'unknown')]:
            run[field] = value
            with self.subTest(field=field):
                attempt = self.build()['query_trace']['queries'][0]['attempts'][0]
                self.assertFalse(attempt['effective'])
                self.assertNotEqual(attempt['status'], 'no_match')
                self.assertFalse(attempt['response_complete'])
            run.clear()
            run.update(deepcopy(saved))
        entry['payload']['candidates'] = [{'title': 'contradicting source card'}]
        attempt = self.build()['query_trace']['queries'][0]['attempts'][0]
        self.assertEqual(attempt['status'], 'unknown')
        self.assertFalse(attempt['effective'])
        self.assertIn('API_DISCOVERY_SOURCE_CARDS_INVALID', attempt['reason'])

    def test_relative_discovery_receipt_uses_original_task_not_supplement_root(self):
        _, run, _, path = self.bounded_discovery()
        run['raw_paths'] = [path.name]
        self.assessment['review']['evidence_root'] = str(self.fixture.root / 'separate-supplement')
        trace = build_query_trace(self.task, self.evidence, self.assessment, self.candidates, self.plan,
            source_task_dir=self.fixture.root)
        self.assertTrue(trace['queries'][0]['response_complete'])
        self.assertEqual(trace['summary']['effective_search_count'], 1)
        self.assertEqual(run['raw_paths'], [path.name])
        self.task['outputs'] = {'assessment_input_dir': str(self.fixture.root)}
        self.assertEqual(trace, build_query_trace(self.task, self.evidence, self.assessment, self.candidates, self.plan))

    def test_all_attempts_preserved_and_actual_query_is_not_plan(self):
        query = self.query()
        first = self.attempt(query)
        self.evidence['collections'][-1]['payload']['candidates'] = [{'candidate_id': 'C1', 'title': 'first real hit'}]
        self.attempt(query, 'R2', 'failed', total=None, retrieved=None, truncated=None, error_code='INTERNAL_PARSE_FAILURE')
        data = self.build()
        trace = data['query_trace']
        self.assertEqual(trace['summary']['attempt_count'], 2)
        self.assertEqual(trace['summary']['effective_search_count'], 1)
        attempts = trace['queries'][0]['attempts']
        self.assertEqual([item['status'] for item in attempts], ['hit', 'failed'])
        self.assertEqual(attempts[0]['actual_query'], '"narrow exact phrase"')
        self.assertEqual(attempts[0]['candidates_found'][0]['title'], 'first real hit')
        self.assertIsNone(attempts[1]['total_hits'])
        self.assertEqual(trace['queries'][0]['status'], 'failed')
        self.assertEqual(trace['queries'][0]['latest_status'], 'failed')
        self.assertTrue(trace['queries'][0]['has_prior_findings'])
        self.assertEqual(trace['queries'][0]['status_label'], '已查到候选；后续查询失败')
        for content in self.rendered(data):
            for expected in ('first real hit', 'INTERNAL_PARSE_FAILURE', 'R1', 'R2', '2025-01-01T00:00:00Z'):
                self.assertIn(expected, content)
            self.assertIn('已查到候选；后续查询失败', content)
            self.assertNotIn(ZERO_WARNING, content)
        self.assertEqual(first['q'], 'planned broad words')

    def test_zero_count_with_retained_candidate_is_contradiction_not_no_match(self):
        query = self.query()
        self.attempt(query, status='no_result', total=0, retrieved=0)
        self.evidence['collections'][-1]['payload']['candidates'] = [{'candidate_id': 'C1', 'title': 'contradicting retained candidate'}]
        data = self.build()
        attempt = data['query_trace']['queries'][0]['attempts'][0]
        self.assertEqual(attempt['status'], 'unknown')
        self.assertTrue(attempt['count_contradiction'])
        self.assertFalse(attempt['effective'])
        self.assertFalse(attempt['coverage_complete'])
        self.assertEqual(data['query_trace']['summary']['unfinished_step_count'], 1)
        for content in self.rendered(data):
            self.assertIn('contradicting retained candidate', content)
            self.assertIn('ZERO_RESULT_CONTRADICTION', content)
            self.assertNotIn('本次成功查询无命中', content)

    def test_states_and_unknown_counts_not_conflated(self):
        cases = [('zero', 'no_result', 0, 0, False, {}, 'no_match'),
            ('partial', 'success', 10, 2, True, {}, 'truncated'),
            ('access', 'access_limited', None, None, None, {}, 'access_limited'),
            ('unknown', 'success', None, None, None, {'submission_state': 'submission_unknown'}, 'submission_unknown'),
            ('skip', 'skipped', None, None, None, {}, 'not_run'),
            ('na', 'not_applicable', None, None, None, {}, 'not_applicable')]
        for identifier, status, total, retrieved, truncated, changes, expected in cases:
            query = self.query(identifier)
            self.attempt(query, identifier, status, total, retrieved, truncated, **changes)
        self.query('planned-only')
        trace = self.build()['query_trace']
        self.assertEqual([item['status'] for item in trace['queries']], [case[-1] for case in cases] + ['not_run'])
        self.assertEqual(trace['queries'][-1]['attempts'], [])
        self.assertEqual(trace['queries'][4]['attempts'][0]['actual_query'], '')
        self.assertEqual(trace['summary']['effective_search_count'], 2)
        self.assertTrue(all(item['attempts'][0]['total_hits'] is None for item in trace['queries'][2:6]))
        self.assertTrue(trace['queries'][0]['coverage_complete'])
        self.assertFalse(any(item.get('query_id') == 'zero' for item in trace['unfinished_work']))

    def test_unplanned_work_and_scope_gaps_are_listed_without_execution(self):
        self.assessment['publication'] = {'remaining_work': [{'work_id': 'WORK-MISSING', 'scenario_id': 'product_entry',
            'jurisdiction': 'US', 'right_type': 'trademark_word', 'kind': 'source_lookup', 'state': 'ready', 'reason': 'API_DISCOVERY_TERMS_MISSING'}]}
        self.assessment['coverage']['scopes'] = [{'scenario_id': 'product_entry', 'jurisdiction': 'US', 'right_type': 'design',
            'verification_status': 'incomplete', 'gaps': ['official status not verified']}]
        trace = self.build()['query_trace']
        self.assertEqual(trace['summary']['unfinished_step_count'], 2)
        self.assertEqual(trace['unfinished_work'][0]['status'], 'not_run')
        self.assertEqual(trace['unfinished_work'][1]['kind'], 'unresolved_scope')

    def test_new_query_notes_wrap_long_diagnostics_after_scenario_prefix(self):
        self.assessment['publication'] = {'remaining_work': [{'work_id': 'WORK-' + 'a' * 24,
            'scenario_id': 'product_entry', 'jurisdiction': 'US', 'right_type': 'design',
            'state': 'blocked', 'reason': 'BOUNDED_DISCOVERY_OFFICIAL_COVERAGE_UNVERIFIED'}]}
        html = report.render_html(self.build(), self.fixture.out)
        self.assertIn('<li><code>product_entry · US · design', html)
        self.assertIn('BOUNDED_DISCOVERY_OFFICIAL_COVERAGE_UNVERIFIED</code></li>', html)
        self.assertIn('<li>plain old prose</li>', report._list_html(['plain old prose']))

    def test_confidence_and_medium_high_critical_are_preserved(self):
        for risk in ('中', '高', '极高'):
            with self.subTest(risk=risk):
                self.row.update(risk=risk, risk_basis='evidence_supported')
                self.assessment['overall'].update(risk=risk, risk_basis='evidence_supported')
                data = self.build()
                self.assertEqual(data['modules'][0]['risk'], risk)
                self.assertEqual(data['modules'][0]['risk_basis'], 'evidence_supported')
                self.assertTrue(all(item['confidence'] == '低' for item in data['modules']))
                self.assertEqual(data['overall']['confidence'], '低')

    def test_zero_search_supported_high_is_not_mislabeled_policy_fallback(self):
        self.row.update(risk='高', risk_basis='evidence_supported')
        self.assessment['overall'].update(risk='高', risk_basis='evidence_supported')
        for content in self.rendered(self.build()):
            self.assertIn('有效检索为零；当前风险由已审阅的具体证据支持', content)
            self.assertNotIn(ZERO_WARNING, content)
        self.assertEqual(self.build()['overall']['risk'], '高')

    def test_copied_plan_query_and_unsubmitted_semantics_are_not_actual_query(self):
        query = self.query()
        run = self.attempt(query)
        run['metadata'].pop('query_semantics')
        self.assertIn('q', run)
        attempt = self.build()['query_trace']['queries'][0]['attempts'][0]
        self.assertEqual(attempt['actual_query'], '')
        self.assertEqual(attempt['actual_query_basis'], 'not_recorded')
        run.update(status='failed', submission_state='not_submitted')
        run['metadata']['query_semantics'] = {'rendered_query': 'compiled but not submitted'}
        attempt = self.build()['query_trace']['queries'][0]['attempts'][0]
        self.assertEqual(attempt['status'], 'failed')
        self.assertEqual(attempt['actual_query'], '')
        self.assertEqual(attempt['actual_query_basis'], 'not_submitted')
        self.assertIn('未记录实际提交内容', report.render_html(self.build(), self.fixture.out))

    def test_low_module_is_policy_fallback_even_with_local_supported_low(self):
        self.row['risk_basis'] = 'evidence_supported'
        data = self.build()
        self.assertEqual(data['modules'][0]['risk_basis'], 'policy_fallback')

    def test_html_escapes_query_and_redacts_source_url_credentials(self):
        query = self.query(q='<script>alert(1)</script>')
        self.attempt(query)
        entry = self.evidence['collections'][-1]
        entry['source_url'] = 'https://user:secret@example.com/results?id=1&api_key=sensitive#secret'
        html = report.render_html(self.build(), self.fixture.out)
        self.assertIn('&lt;script&gt;', html)
        self.assertNotIn('<script>', html)
        self.assertNotIn('sensitive', html)
        self.assertNotIn('user:secret', html)
        self.assertIn('https://example.com/results?id=1', html)

    def test_manifest_binds_query_trace_and_eight_sections_css_unchanged(self):
        data = self.build()
        payloads = report.bundle_bytes(data, self.fixture.out)
        manifest = report._manifest(data, payloads)
        self.assertEqual(manifest['query_trace']['sha256'], report._digest(data['query_trace']))
        self.assertEqual(manifest['assessment_revision'], 'partial-evidence-v1')
        self.assertEqual(manifest['template_css_sha256'], report._sha(report.CSS_PATH.read_bytes()))
        html = payloads['report.html'].decode()
        self.assertEqual(html.count('<section id='), 8)
        self.assertEqual(len(data['modules']), 7)
        self.assertEqual(json.loads(payloads['report-data.json'])['query_trace'], data['query_trace'])

    def test_historical_and_complete_tasks_keep_legacy_rendering(self):
        self.task.pop('assessment_revision')
        self.assessment.pop('assessment_revision')
        self.row.update(risk='中', aggregation_included=True)
        self.row.pop('risk_aggregation_included')
        self.assessment['status'] = 'completed'
        self.assessment['overall'].update(business_completion='complete', risk='中')
        self.assessment['overall']['confidence'] = '高'
        self.row['evidence_confidence'] = '高'
        legacy = self.build()
        self.task['assessment_revision'] = 'partial-evidence-v1'
        current = self.build()
        self.assertNotIn('query_trace', current)
        for old, new in zip(self.rendered(legacy), self.rendered(current)):
            # Task input digest legitimately changes; presentation semantics do not.
            self.assertEqual(old.replace(legacy['trace']['input_digests']['task'], ''), new.replace(current['trace']['input_digests']['task'], ''))
        self.assertNotIn('查询未完成', report.render_html(current, self.fixture.out))
        self.assertIn('高置信度', report.render_html(current, self.fixture.out))

    def test_nested_browser_semantics_zero_observation_keeps_unknown_coverage(self):
        query = self.query(search_dimension='text', search_language='en')
        run = self.attempt(query, status='no_result', total=0, retrieved=0)
        run['metadata'].pop('query_semantics')
        coverage = run['metadata']['search_coverage']
        coverage.pop('total_hits')
        coverage.update(completeness='unknown', reported_total=0, reviewed_hits=None, pages_retrieved=1,
            query_semantics={'rendered_query': '"miniature angle grinder keychain"', 'semantics': 'lexical_phrase'})
        trace = self.build()['query_trace']
        actual = trace['queries'][0]['attempts'][0]
        self.assertEqual(actual['actual_query'], '"miniature angle grinder keychain"')
        self.assertEqual(actual['status'], 'no_match')
        self.assertEqual(actual['total_hits'], 0)
        self.assertFalse(actual['coverage_complete'])
        self.assertEqual(actual['pages_retrieved'], 1)
        self.assertEqual(trace['summary']['unfinished_step_count'], 1)
        self.assertEqual(trace['queries'][0]['search_language'], 'en')
        for content in self.rendered(self.build()):
            self.assertIn('本次查询无命中', content)
            self.assertIn('召回覆盖：未完成或未知', content)

    def test_legacy_receipt_without_completeness_uses_existing_count_stop_contract(self):
        query = self.query()
        run = self.attempt(query)
        self.evidence['collections'][-1]['payload']['candidates'] = [{'candidate_id': 'C1', 'title': 'recorded hit'}]
        trace = self.build()['query_trace']
        self.assertTrue(trace['queries'][0]['coverage_complete'])
        self.assertEqual(trace['queries'][0]['attempts'][0]['completeness'], 'not_recorded')
        self.assertEqual(trace['summary']['unfinished_step_count'], 0)
        coverage = run['metadata']['search_coverage']
        for key, value in [('completeness', 'unknown'), ('stop_reason', ''), ('total_hits', 2), ('schema_valid', False)]:
            original = deepcopy(coverage)
            with self.subTest(key=key):
                coverage[key] = value
                trace = self.build()['query_trace']
                self.assertFalse(trace['queries'][0]['coverage_complete'])
                self.assertEqual(trace['summary']['unfinished_step_count'], 1)
            coverage.clear()
            coverage.update(original)
        self.evidence['collections'][-1]['payload']['candidates'] = []
        self.assertFalse(self.build()['query_trace']['queries'][0]['coverage_complete'])

    def test_raw_plan_hash_and_exact_scenario_version_binding(self):
        query = self.query(scenario_bindings=[{'scenario_id': 'entry', 'scenario_sha256': 'a' * 64}])
        query.pop('provider')
        self.attempt(query)
        self.attempt(query, 'OLD', plan_entry_sha256='b' * 64)
        self.assessment['coverage']['scopes'] = [
            {'scenario_id': 'entry', 'scenario_sha256': letter * 64, 'jurisdiction': 'US', 'right_type': 'design'}
            for letter in ('a', 'b')]
        trace = self.build()['query_trace']
        self.assertEqual(len(trace['queries'][0]['attempts']), 1)
        self.assertEqual(trace['queries'][0]['attempts'][0]['run_id'], 'R1')
        self.assertTrue(trace['queries'][1]['historical_unplanned_run'])
        self.assertEqual(trace['summary']['effective_search_count'], 1)
        old_scope = next(item for item in trace['dimensions'] if item['scenario_sha256'] == 'b' * 64)
        self.assertEqual(old_scope['query_indices'], [])
        for content in self.rendered(self.build())[:2]:
            self.assertIn('[情景版本 aaaaaaaaaaaa]', content)
            self.assertIn('[情景版本 bbbbbbbbbbbb]', content)

    def test_existing_requirement_array_avoids_duplicate_unplanned_work(self):
        self.task['coverage_requirements'] = [{'requirement_id': 'REQ1', 'jurisdiction': 'US', 'right_type': 'patent', 'phase': 'official_recall'}]
        self.assessment['publication'] = {'remaining_work': [{'work_id': 'WORK1', 'requirement_ids': ['REQ1'],
            'jurisdiction': 'US', 'right_type': 'patent', 'state': 'ready'}]}
        self.assertEqual(self.build()['query_trace']['summary']['unfinished_step_count'], 1)

    def test_new_risk_reasoning_does_not_display_legacy_pending_no_grade(self):
        self.row.update(reasoning='原审阅记录：不给风险结论', risk_reasoning='新的规则兜底评级理由')
        for content in self.rendered(self.build()):
            self.assertIn('新的规则兜底评级理由', content)
            self.assertNotIn('原审阅记录：不给风险结论', content)

    def test_legacy_extra_risk_reasoning_does_not_override_historical_reasoning(self):
        row = {'reasoning': 'historical reasoning', 'risk_reasoning': 'unrecognized extra field'}
        self.assertEqual(report._reason_value(row, 'reasoning'), 'historical reasoning')
        row['risk_basis'] = 'policy_fallback'
        self.assertEqual(report._reason_value(row, 'reasoning'), 'unrecognized extra field')


if __name__ == '__main__':
    unittest.main()
