"""The last free detail requests are kept for the document the product itself claims (host-triage tasks only)."""
import unittest

import candidate_api_actions as actions

TASK = {'serpapi_free_enhancement': {'max_queries_per_task': 10}, 'host_triage_revision': 'host-triage-v1',
        'retrieval_workflow_revision': 'not-api-first-v3'}
LEAD = {'collections': {'candidate_leads': [{'lead': {'publication_number': 'US 11,401,089 B2'}}]}, 'source_runs': []}
OTHER = {'candidate_id': 'C-other', 'publication_number': 'US20250318691A1', 'sources': [{'provider': 'serpapi_google_patents'}]}
OWN = {'candidate_id': 'C-lead', 'publication_number': 'US11401089B2', 'sources': [{'provider': 'external_document_lead'}]}


def detail_rows(*numbers):
    return {'serpapi_google_patents': [{'query_id': 'Q%d' % index, 'operation': 'candidate_detail', 'q': number}
                                       for index, number in enumerate(numbers)]}


class LeadQuotaReserveTests(unittest.TestCase):
    def test_other_candidates_are_held_one_below_the_cap_per_unfunded_lead(self):
        queries = detail_rows(*['US2025%07dA1' % n for n in range(9)])      # 9 planned of 10
        reserve = actions._lead_reserve(TASK, LEAD, queries, OTHER)
        self.assertEqual(reserve, 1)
        self.assertEqual(actions._budget_issue(TASK, LEAD, queries, 'serpapi_google_patents', reserve=reserve),
                         'FREE_TASK_PLAN_LIMIT_REACHED')
        # without the reserve the same request would still have fitted
        self.assertEqual(actions._budget_issue(TASK, LEAD, queries, 'serpapi_google_patents'), '')

    def test_two_unfunded_leads_hold_two_slots_and_never_more(self):
        two = {'collections': {'candidate_leads': [{'lead': {'publication_number': 'US11401089B2'}},
                                                   {'lead': {'publication_number': 'USD0900000S'}},
                                                   {'lead': {'publication_number': 'US10000001B2'}}]},
               'source_runs': []}
        self.assertEqual(actions._lead_reserve(TASK, two, detail_rows(), OTHER), 2)

    def test_the_lead_itself_is_never_held_back_and_can_use_the_reserved_slots(self):
        queries = detail_rows(*['US2025%07dA1' % n for n in range(9)])
        self.assertEqual(actions._lead_reserve(TASK, LEAD, queries, OWN), 0)
        self.assertEqual(actions._budget_issue(TASK, LEAD, queries, 'serpapi_google_patents', reserve=0), '')

    def test_reserve_is_released_once_the_leads_own_request_is_planned(self):
        queries = detail_rows(*['US2025%07dA1' % n for n in range(7)], 'US11401089B2')
        self.assertEqual(actions._lead_reserve(TASK, LEAD, queries, OTHER), 0)

    def test_no_lead_means_no_reserve_and_legacy_tasks_are_untouched(self):
        queries = detail_rows('US20250000001A1')
        self.assertEqual(actions._lead_reserve(TASK, {'collections': {}, 'source_runs': []}, queries, OTHER), 0)
        legacy = {key: value for key, value in TASK.items() if key != 'host_triage_revision'}
        self.assertEqual(actions._lead_reserve(legacy, LEAD, queries, OTHER), 0)

    def test_a_cap_not_larger_than_the_reserve_is_never_starved(self):
        task = {**TASK, 'serpapi_free_enhancement': {'max_queries_per_task': 2}}
        self.assertEqual(actions._budget_issue(task, LEAD, {}, 'serpapi_google_patents', reserve=2), '')

    def test_other_providers_are_unaffected(self):
        self.assertEqual(actions._budget_issue(TASK, LEAD, {}, 'epo_ops', reserve=2), '')


if __name__ == '__main__':
    unittest.main()
