"""The identity card must not send a non-Lens seller page to the Lens-only public recorder."""
import tempfile
import unittest
from pathlib import Path

from common import atomic_write_json


def lens_candidate(cid):
    return {'candidate_id': cid, 'right_type': 'unknown', 'source_index': 'google_lens', 'match_type': 'visual_matches',
            'sources': [{'provider': 'serpapi_google_lens', 'source_collection': 'visual_matches',
                         'identity_observation': {'identifiers': {}}}]}


def serper_candidate(cid):
    return {'candidate_id': cid, 'right_type': 'unknown', 'source_index': 'google_images', 'match_type': 'visual_match',
            'sources': [{'provider': 'serper_images', 'source_collection': 'images',
                         'identity_observation': {'identifiers': {}}}]}


class IdentityRouteCardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        atomic_write_json(self.root / 'task.json', {'task_id': 'T', 'retrieval_workflow_revision': 'api-first-v3',
                                                    'public_discovery_routing_revision': 'public-discovery-v1'})
        atomic_write_json(self.root / 'normalized-candidates.json', {
            'copyright_assets': [lens_candidate('CAND-LENS'), serper_candidate('CAND-SERPER')], 'patents': []})

    def card(self, cid):
        from advance_work import action_card
        entry = {'work_id': 'W-' + cid, 'kind': 'agent_investigation', 'state': 'awaiting_review',
                 'reason': 'CANDIDATE_IDENTITY_DIRECTION_PENDING', 'candidate_id': cid, 'scenario_id': 'S',
                 'jurisdiction': 'UNLOCATED', 'right_type': 'unknown'}
        return action_card(self.root, entry)

    def test_lens_sales_lead_keeps_the_bounded_public_recorder(self):
        card = self.card('CAND-LENS')
        self.assertTrue(card['bounded_public_recorder'].endswith('record_public_identity.py'))
        self.assertEqual(card['identity_route'], {'public_identity': 'applicable'})

    def test_other_source_names_the_routes_that_exist_instead_of_the_lens_recorder(self):
        card = self.card('CAND-SERPER')
        self.assertIsNone(card['bounded_public_recorder'])
        route = card['identity_route']
        self.assertEqual(route['public_identity'], 'not_applicable')
        self.assertEqual(route['source_providers'], ['serper_images'])
        self.assertEqual(len(route['routes']), 3)
        self.assertIn('user_information', ' '.join(route['routes']))

    def test_unreadable_candidates_fall_back_to_the_previous_card(self):
        (self.root / 'normalized-candidates.json').unlink()
        card = self.card('CAND-SERPER')
        self.assertTrue(card['bounded_public_recorder'].endswith('record_public_identity.py'))
        self.assertNotIn('identity_route', card)


class SerperRouteV2Tests(IdentityRouteCardTests):
    """best-estimate-risk-v2 tasks: a Serper Google Images sales card uses the same bounded public recorder."""
    def setUp(self):
        super().setUp()
        atomic_write_json(self.root / 'task.json', {'task_id': 'T', 'retrieval_workflow_revision': 'api-first-v3',
            'public_discovery_routing_revision': 'public-discovery-v1',
            'assessment_revision': 'known-findings-risk-v1', 'best_estimate_revision': 'best-estimate-risk-v2'})

    def test_other_source_names_the_routes_that_exist_instead_of_the_lens_recorder(self):
        card = self.card('CAND-SERPER')
        self.assertTrue(card['bounded_public_recorder'].endswith('record_public_identity.py'))
        self.assertEqual(card['identity_route'], {'public_identity': 'applicable'})

    def test_serper_reference_without_collection_name_and_identifiers(self):
        from public_identity import public_sales_lead
        from common import load_json
        task = load_json(self.root / 'task.json')
        bare = serper_candidate('C')
        bare['sources'][0].pop('source_collection')
        self.assertTrue(public_sales_lead(task, bare))
        numbered = serper_candidate('C')
        numbered['sources'][0]['identity_observation'] = {'identifiers': {'publication_number': 'US1'}}
        self.assertFalse(public_sales_lead(task, numbered))
        other = serper_candidate('C')
        other['sources'][0]['provider'] = 'serper_web'
        self.assertFalse(public_sales_lead(task, other))
        self.assertFalse(public_sales_lead({**task, 'best_estimate_revision': 'best-estimate-risk-v1'}, bare))


if __name__ == '__main__':
    unittest.main()
