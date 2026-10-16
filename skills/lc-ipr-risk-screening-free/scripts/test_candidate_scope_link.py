"""Program-recorded candidate scope links: unambiguous cases only, via the real scope recorder."""
from contextlib import redirect_stdout
from io import StringIO
import unittest

from common import atomic_write_json, load_json


class CandidateScopeLinkTests(unittest.TestCase):
    def setUp(self):
        import test_product_scope
        self.scope = test_product_scope.ScopeTests()
        with redirect_stdout(StringIO()):
            self.scope.setUp()
        self.addCleanup(self.scope.doCleanups)
        objects = self.scope.data['scope']['objects']
        for row in objects:
            # Only the pattern object may be compared with copyright candidates.
            if row['object_id'] in {'photo', 'box'}:
                row['right_types'] = ['enforcement']
        with redirect_stdout(StringIO()):
            self.task = self.scope.save()
        self.run = self.scope.run
        self.source = self.task['product_identity']['evidence_id']

    def candidates(self, *rows):
        payload = {'task_id': self.task['task_id'], 'patents': [], 'trademarks': [], 'enforcement': [],
                   'copyright_assets': list(rows)}
        atomic_write_json(self.run / 'normalized-candidates.json', payload)

    def candidate(self, cid, right='copyright', sources=True):
        row = {'candidate_id': cid, 'right_type': right, 'title': 'Candidate ' + cid, 'jurisdiction': 'US'}
        if sources:
            row['sources'] = [{'evidence_id': self.source, 'provider': 'serper_images'}]
        return row

    def test_unambiguous_candidates_are_linked_once_through_the_scope_recorder(self):
        import candidate_scope_link as link
        self.candidates(self.candidate('CAND-A'), self.candidate('CAND-B'))
        before = load_json(self.run / 'task.json')['product_scope']['scope_sha256']
        with redirect_stdout(StringIO()):
            receipt = link.auto_link(self.run)
        self.assertEqual(receipt['linked'], 2)
        self.assertEqual(receipt['status'], 'success')
        task = load_json(self.run / 'task.json')
        self.assertNotEqual(task['product_scope']['scope_sha256'], before)
        rows = {row['candidate_id']: row for row in task['product_scope']['candidate_links']}
        self.assertEqual(set(rows), {'CAND-A', 'CAND-B'})
        self.assertEqual(rows['CAND-A']['object_ids'], ['pattern'])
        self.assertEqual(rows['CAND-A']['source_refs'], [self.source])
        self.assertIn('分流决定', rows['CAND-A']['reason'])
        # Facts, objects and directions are carried over unchanged.
        self.assertEqual(task['product_scope']['facts'], self.task['product_scope']['facts'])
        self.assertEqual(task['product_scope']['directions'], self.task['product_scope']['directions'])
        self.assertEqual(task.get('product_change_version'), self.task.get('product_change_version'))
        with redirect_stdout(StringIO()):
            again = link.auto_link(self.run)
        self.assertEqual(again['linked'], 0)
        self.assertEqual(load_json(self.run / 'task.json')['product_scope']['candidate_links'],
                         task['product_scope']['candidate_links'])

    def test_ambiguous_or_unsourced_candidates_stay_with_the_agent(self):
        import candidate_scope_link as link
        # Enforcement is declared only by objects that are not included.
        self.candidates(self.candidate('CAND-E', right='enforcement'), self.candidate('CAND-N', sources=False),
                        self.candidate('CAND-OK'))
        with redirect_stdout(StringIO()):
            receipt = link.auto_link(self.run)
        reasons = {row['candidate_id']: row['reason'] for row in receipt['skipped']}
        self.assertEqual(reasons['CAND-E'], 'NO_INCLUDED_COMPATIBLE_OBJECT')
        self.assertEqual(reasons['CAND-N'], 'NO_RETAINED_SOURCE_EVIDENCE')
        self.assertEqual(receipt['candidate_ids'], ['CAND-OK'])

    def test_planned_object_of_the_candidates_own_query_narrows_the_link(self):
        import candidate_scope_link as link
        for row in self.scope.data['scope']['objects']:
            if row['object_id'] in {'photo', 'box'}:
                row['right_types'] = ['copyright']      # excluded objects now also cover copyright
        with redirect_stdout(StringIO()):
            self.scope.update()
        evidence = load_json(self.run / 'evidence.json')
        evidence['source_runs'].append({'run_id': 'RUN-L', 'query_id': 'Q-L', 'provider': 'synthetic'})
        atomic_write_json(self.run / 'evidence.json', evidence)
        atomic_write_json(self.run / 'search-plan.json', {'queries': {'synthetic': [{'query_id': 'Q-L',
            'product_dependencies': [{'direction_id': 'pattern', 'object_ids': ['pattern']}]}]}})
        planned = self.candidate('CAND-P')
        planned['sources'] = [{'evidence_id': self.source, 'source_run_id': 'RUN-L'}]
        self.candidates(planned, self.candidate('CAND-U'))
        with redirect_stdout(StringIO()):
            receipt = link.auto_link(self.run)
        self.assertEqual(receipt['candidate_ids'], ['CAND-P', 'CAND-U'])
        rows = {row['candidate_id']: row for row in load_json(self.run / 'task.json')['product_scope']['candidate_links']}
        # Excluded photo/box objects also cover copyright but are never linked here.
        self.assertEqual(rows['CAND-P']['object_ids'], ['pattern'])
        self.assertIn('Q-L', rows['CAND-P']['reason'])
        self.assertEqual(rows['CAND-U']['object_ids'], ['pattern'])
        self.assertNotIn('Q-L', rows['CAND-U']['reason'])

    def test_existing_agent_link_is_preserved_and_dry_run_writes_nothing(self):
        import candidate_scope_link as link
        self.scope.data['scope']['candidate_links'] = [{'candidate_id': 'CAND-A', 'object_ids': ['pattern'],
            'reason': 'Agent reviewed link', 'source_refs': [self.source]}]
        self.candidates(self.candidate('CAND-A'), self.candidate('CAND-B'))
        with redirect_stdout(StringIO()):
            self.task = self.scope.update()
        sha = self.task['product_scope']['scope_sha256']
        with redirect_stdout(StringIO()):
            planned = link.auto_link(self.run, dry_run=True)
        self.assertEqual(planned['candidate_ids'], ['CAND-B'])
        self.assertEqual(load_json(self.run / 'task.json')['product_scope']['scope_sha256'], sha)
        self.assertFalse((self.run / link.OUTPUT_DIR).exists())
        with redirect_stdout(StringIO()):
            link.auto_link(self.run)
        links = {row['candidate_id']: row for row in load_json(self.run / 'task.json')['product_scope']['candidate_links']}
        self.assertEqual(links['CAND-A']['reason'], 'Agent reviewed link')
        self.assertEqual(links['CAND-B']['object_ids'], ['pattern'])

    def test_missing_candidates_or_scope_are_reported_not_raised(self):
        import candidate_scope_link as link
        with redirect_stdout(StringIO()):
            self.assertEqual(link.auto_link(self.run)['status'], 'no_candidates')
        links, skipped = link.plan_links({}, {'copyright_assets': [self.candidate('X')]})
        self.assertEqual(links, [])
        self.assertEqual(skipped[0]['reason'], 'PRODUCT_SCOPE_NOT_ENABLED')


if __name__ == '__main__':
    unittest.main()
