"""Discovery-result review template (prefilled digest) and the atomic multi-review recorder."""
from unittest.mock import patch
import unittest

from common import load_json


class DiscoveryReviewBatchTests(unittest.TestCase):
    def setUp(self):
        import test_api_first_planning as base
        self.base = base.ApiFirstPlanningTests('test_initial_api_only_plus_specialties_and_bounded_contract')
        self.base.setUp()
        self.addCleanup(self.base.tearDown)
        self.path = self.base.path

    def entries(self):
        from api_first_planning import next_work_entries
        b = self.base
        task = load_json(self.path / 'task.json')
        plan = load_json(self.path / 'search-plan.json')
        evidence = load_json(self.path / 'evidence.json')
        rows = next_work_entries(task, plan, evidence, b.candidates, b.ledger)
        return [{**row, 'work_id': 'WORK-%d' % index} for index, row in enumerate(rows)]

    def template(self):
        import input_template as it
        entries = self.entries()
        review = [e for e in entries if e.get('reason') == 'API_DISCOVERY_REVIEW_REQUIRED']
        self.assertTrue(review, [e.get('reason') for e in entries])
        with patch('workflow_v24.work_view_from_dir', return_value={'entries': entries}):
            files, summaries, skipped = it.build(self.path)
        return files, summaries, skipped, review

    def test_template_prefills_run_evidence_and_the_exact_triage_digest(self):
        from api_first_planning import triage_digest
        b = self.base
        run = b.source(status='no_result')
        files, summaries, skipped, review = self.template()
        rows = files['discovery-review.json']['reviews']
        row = next(r for r in rows if r['query_id'] == b.primary()['query_id'])
        self.assertEqual(row['source_run_id'], run['run_id'])
        self.assertIn('EV-' + run['run_id'], row['evidence_ids'])
        self.assertEqual(row['triage_digest'], triage_digest(b.task, load_json(self.path / 'evidence.json'),
                                                             b.candidates, b.ledger, query_id=b.primary()['query_id']))
        self.assertEqual((row['reviewer'], row['reason'], row['outcome']), (None, None, None))
        summary = next(s for s in summaries if s['file'] == 'discovery-review.json')
        self.assertEqual(sorted(summary['fill']), ['outcome', 'reason', 'reviewer'])
        self.assertEqual(summary['recorder'], 'record_discovery_review.py')

    def test_failed_run_template_asks_for_a_blocker_not_a_digest(self):
        b = self.base
        b.source(status='failed')
        files, summaries, skipped, review = self.template()
        row = next(r for r in files['discovery-review.json']['reviews'] if r['query_id'] == b.primary()['query_id'])
        self.assertIn('blocker', row)
        self.assertNotIn('triage_digest', row)

    def test_batch_records_atomically_and_rejects_the_whole_batch_on_one_bad_review(self):
        import record_discovery_review as rec
        b = self.base
        b.source(status='no_result')
        files, _, _, _ = self.template()
        good = dict(next(r for r in files['discovery-review.json']['reviews'] if r['query_id'] == b.primary()['query_id']))
        good.update(reviewer='unit-agent', outcome='stop_bounded_discovery',
                    reason='Only the one-page discovery scope was reviewed; official coverage remains unresolved')
        bad = {**good, 'query_id': 'UNKNOWN-QUERY'}
        before = load_json(self.path / 'task.json').get('discovery_followups', [])
        with self.assertRaises(ValueError):
            rec.record_batch(self.path, [good, bad])
        self.assertEqual(load_json(self.path / 'task.json').get('discovery_followups', []), before)
        self.assertEqual(rec.record_batch(self.path, [good]), [b.primary()['query_id']])
        saved = load_json(self.path / 'task.json')['discovery_followups'][-1]
        self.assertEqual((saved['role'], saved['outcome']), ('review', 'stop_bounded_discovery'))
        with self.assertRaises(ValueError):
            rec.record_batch(self.path, [good, {**good}])      # duplicate query id in one batch

    def test_stale_digest_after_new_triage_is_rejected(self):
        import record_discovery_review as rec
        b = self.base
        b.source(status='no_result')
        files, _, _, _ = self.template()
        row = dict(next(r for r in files['discovery-review.json']['reviews'] if r['query_id'] == b.primary()['query_id']))
        row.update(reviewer='unit-agent', outcome='stop_bounded_discovery', reason='Reviewed', triage_digest='0' * 64)
        with self.assertRaisesRegex(ValueError, 'TRIAGE_CHANGED'):
            rec.record_batch(self.path, [row])


if __name__ == '__main__':
    unittest.main()
