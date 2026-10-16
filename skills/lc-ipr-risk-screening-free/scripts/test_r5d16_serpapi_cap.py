"""r5d16: new tasks may use 20 SerpApi requests (owner decision); a task keeps the cap it was created with.

B0GLNPC6K8 r5d12 task needed 12 (1 search, one exact record for each of the 8 selected patents and designs, 3 for
candidates the screen then found dead); at 10, two selected patents went without their exact record.
"""
import json
import unittest
from pathlib import Path
from unittest import mock

import api_first_planning
import common

CONFIG = Path(__file__).resolve().parents[1] / 'references' / 'runtime-config.json'


def task(cap, policy=None):
    value = common.serpapi_free_enhancement(True, common.API_FIRST_V3_REVISION)
    value['max_queries_per_task'] = cap
    return {'retrieval_workflow_revision': common.API_FIRST_V3_REVISION, 'serpapi_free_enhancement': value,
            'retrieval_policy': {} if policy is None else {'serpapi_max_requests': policy}}


class SerpApiCapTests(unittest.TestCase):
    def test_the_configured_and_contracted_cap_is_twenty(self):
        self.assertEqual(json.loads(CONFIG.read_text(encoding='utf-8'))['api_first']['serpapi_max_requests'], 20)
        self.assertEqual(common.SERPAPI_API_FIRST_MAX_QUERIES_PER_TASK, 20)

    @mock.patch.object(common, 'api_first_enabled', return_value=True)
    def test_a_task_keeps_the_cap_it_was_created_with(self, _):
        new, old = task(20, 20), task(10, 10)
        self.assertEqual(common.serpapi_free_enhancement_error(new), '')
        self.assertEqual(common.serpapi_free_enhancement_error(old), '')
        self.assertEqual(api_first_planning._limits(new)['serpapi'], 20)
        self.assertEqual(api_first_planning._limits(old)['serpapi'], 10)
        self.assertEqual(common.serpapi_free_enhancement_error(task(21, 20)), 'SERPAPI_FREE_ENHANCEMENT_INVALID')
        with self.assertRaisesRegex(ValueError, 'API_FIRST_RETRIEVAL_POLICY_INVALID'):
            api_first_planning._limits(task(20, 21))


if __name__ == '__main__':
    unittest.main()
