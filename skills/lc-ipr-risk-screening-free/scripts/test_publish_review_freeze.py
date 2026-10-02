"""Publishing rejects changed review inputs before recording a build."""
import unittest
from pathlib import Path
from unittest.mock import patch
import publish_report


class PublishReviewFreezeTests(unittest.TestCase):
    def test_stale_pair_fails_before_delivery_build_mutation(self):
        with patch.object(publish_report, '_assert_review_pair_current',
                          side_effect=ValueError('REPORT_REVIEW_INPUT_CHANGED: first')), \
             patch('delivery_versions_stage_e.enabled', return_value=True), \
             patch('delivery_versions_stage_e.begin_build') as begin:
            with self.assertRaisesRegex(ValueError, 'REPORT_REVIEW_INPUT_CHANGED'):
                publish_report.publish(Path('/task'), Path('/first'), Path('/second'),
                                       output_dir=Path('/new-output'))
        begin.assert_not_called()

    def test_current_pair_digest_must_match_both_reviewers(self):
        from publish_report import _assert_review_pair_current
        task_dir = Path('/task')
        first, second = {'review_context': {'evidence_digest': 'current'}}, {
            'review_context': {'evidence_digest': 'old'}}
        with patch('workflow_v24._scenario_context', return_value=({}, {}, {})), \
             patch('workflow_v24.scenario_supplement', return_value={}), \
             patch('assessment_estimate.review_digest', return_value='current'), \
             patch('publish_report.load_json', side_effect=[{'task_id': 'T'}, {'queries': {}}, first, second]):
            with self.assertRaisesRegex(ValueError, 'REPORT_REVIEW_INPUT_CHANGED: second'):
                _assert_review_pair_current(task_dir, Path('/first'), Path('/second'))


if __name__ == '__main__':
    unittest.main()
