"""Synthetic candidate-local recapture tests; original evidence is never rewritten."""
from copy import deepcopy
import unittest

import decision_workflow as workflow


class CandidateCaptureMetadataTests(unittest.TestCase):
    def setUp(self):
        self.task = {'decision_workflow_revision': workflow.REVISION,
                     'workflow_correction_revision': workflow.CORRECTION_REVISION}
        self.candidate = {'publication_number': 'US11111111B2', 'jurisdiction': 'US',
                          'right_type': 'patent', 'evidence_refs': ['E1']}
        self.record = {**deepcopy(self.candidate), 'title': 'Synthetic retaining strap',
                       'result_ordinal': 2, 'browser_evidence': {
                           'screenshot_path': '/synthetic/first.png',
                           'screenshot_sha256': 'a' * 64, 'screenshot_bytes': 100}}
        self.evidence = {'collections': {'patents': [
            {'evidence_id': 'E1', 'payload': {'candidates': [self.record]}}]}}

    def digest(self, task=None):
        return workflow.candidate_content_sha256(self.candidate, self.evidence,
                                                 task=self.task if task is None else task)

    def test_repeat_result_capture_and_position_are_not_new_facts(self):
        before = self.digest()
        old_source = deepcopy(self.evidence)
        new = deepcopy(self.record)
        new['result_ordinal'] = 100
        new['browser_evidence'].update(screenshot_path='/synthetic/later.png',
                                      screenshot_sha256='b' * 64, screenshot_bytes=200)
        self.evidence['collections']['patents'].append(
            {'evidence_id': 'E2', 'payload': {'candidates': [new]}})
        self.candidate['evidence_refs'].append('E2')
        self.assertEqual(before, self.digest())
        self.assertEqual(old_source['collections']['patents'][0], self.evidence['collections']['patents'][0])

    def test_substantive_title_claim_status_and_visual_facts_remain_bound(self):
        for field, value in [('title', 'Different mechanism'), ('claims', 'A changed claim'),
                             ('legal_status', 'expired'), ('drawing_sha256', 'c' * 64)]:
            with self.subTest(field=field):
                before = self.digest()
                old = deepcopy(self.record)
                self.record[field] = value
                self.assertNotEqual(before, self.digest())
                self.record.clear()
                self.record.update(old)
        before = self.digest()
        self.record['browser_evidence']['candidate_figure_sha256'] = 'd' * 64
        self.assertNotEqual(before, self.digest())

    def test_historical_branch_retains_prior_semantics(self):
        legacy = {'decision_workflow_revision': workflow.REVISION}
        before = self.digest(legacy)
        self.record['result_ordinal'] = 100
        self.assertNotEqual(before, self.digest(legacy))


if __name__ == '__main__':
    unittest.main()
