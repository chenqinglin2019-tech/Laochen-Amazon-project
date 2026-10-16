"""r5d21 precision-v1: the list screen is the triage, deep checks are capped, dead US cards leave by rule."""
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import precision
import recall
import recall_screen
import test_text_triage_host as text_fixture
from common import atomic_write_json, load_json


class PreciseTextFixture(text_fixture.TextHostFixture):
    def setUp(self):
        super().setUp()
        task = load_json(self.root / 'task.json')
        task.update(recall_revision=recall.REVISION, candidate_precision_revision=precision.REVISION)
        atomic_write_json(self.root / 'task.json', task)
        self.answers = {}

    def screen_native(self, command, prompt, workspace, trace_path, stderr_path, timeout):
        packet = load_json(trace_path.parent / 'packet.json')
        self.calls.append(sorted(unit['template']['candidate_id'] for unit in packet['units']))
        rows = [{'id': unit['unit_id'], **self.answers[unit['template']['candidate_id']]}
                for unit in packet['units'] if unit['template']['candidate_id'] in self.answers]
        stderr_path.write_text('')
        events = [{'type': 'thread.started', 'thread_id': 'screen-1'}, {'type': 'turn.started'},
                  {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps({'decisions': rows})}},
                  {'type': 'turn.completed'}]
        text = '\n'.join(map(json.dumps, events))
        trace_path.write_text(text)
        return SimpleNamespace(returncode=0, pid=7001), text, ''

    def screen(self):
        with mock.patch('report_review_host.run_native_logged', side_effect=self.screen_native), \
                mock.patch('review_isolation.select_backend', return_value='macos-sandbox'), \
                mock.patch('native_review_jobs._probe', return_value=[]), \
                mock.patch('macos_review_host.require_chatgpt_auth'), redirect_stdout(StringIO()):
            return recall_screen.run(self.root, binary=self.binary, isolation='macos-sandbox', mode='text')

    def latest(self):
        rows = {}
        for row in self.annotations():
            rows[row['candidate_id']] = row
        return rows


class ScreenIsTriageTests(PreciseTextFixture):
    def test_named_cards_are_selected_with_the_sessions_sentence_and_the_rest_leave(self):
        self.answers = {'P0': {'tier': 'core', 'relationship': '候选的折叠支架与锁扣结构对应产品的锁定机构'}}
        summary = self.screen()
        self.assertEqual(self.calls, [['P0', 'P1', 'P2']])        # every card is screened, even a set of three
        rows = self.latest()
        self.assertEqual(rows['P0']['decision'], 'selected')
        self.assertEqual(rows['P0']['reason'], '候选的折叠支架与锁扣结构对应产品的锁定机构')
        self.assertEqual(rows['P0']['reviewer'], 'native-recall-screen-screen-1')
        self.assertEqual(rows['P1']['decision'], 'not_selected')
        self.assertNotIn('P2', rows)                               # a title-only card is never excluded on its card
        self.assertEqual(summary['text_selection']['selected'], 1)
        import core_focus
        self.assertEqual(core_focus.priorities(self.root).get('P0'), 'core')

    def test_cards_over_the_cap_are_recorded_as_not_deep_checked(self):
        self.answers = {'P0': {'tier': 'related', 'relationship': '候选涉及与产品相同的锁定机构'},
                        'P1': {'tier': 'core', 'relationship': '候选与产品同为折叠支架'}}
        with mock.patch.object(precision, 'UTILITY_CAP', 1):
            summary = self.screen()
        rows = self.latest()
        self.assertEqual(rows['P1']['decision'], 'selected')       # core ranks before related
        self.assertEqual(rows['P0']['decision'], 'not_selected')
        self.assertEqual(rows['P0']['reviewer'], recall_screen.CAP_REVIEWER)
        self.assertIn('超出本轮深查上限', rows['P0']['reason'])
        self.assertEqual(summary['text_selection'], {'selected': 1, 'over_cap': 1, 'recorded': 2, 'rejected': []})

    def test_an_invalid_answer_never_decides_its_card(self):
        self.answers = {'P0': {'tier': 'maybe', 'relationship': 'x'}}
        summary = self.screen()
        rows = self.latest()
        self.assertNotIn('P0', rows)                               # retried in halves, still invalid: left pending
        self.assertIn('P0', [row['candidate_id'] for row in summary['text']['unresolved']])
        self.assertEqual(rows['P1']['decision'], 'not_selected')   # its own valid session listed nothing


class TierParsingTests(unittest.TestCase):
    PACKET = {'screen_mode': 'image', 'units': [{'unit_id': 'A'}, {'unit_id': 'B'}]}

    def test_tiers_and_sentences(self):
        raw = {'decisions': [{'id': 'A', 'tier': 'same', 'relationship': '同为圆筒网篮，主体相同'}]}
        self.assertEqual(recall_screen.tiered(raw, self.PACKET), {'A': ('same', '同为圆筒网篮，主体相同')})
        for bad in ({'decisions': [{'id': 'C', 'tier': 'same', 'relationship': 'x'}]},
                    {'decisions': [{'id': 'A', 'tier': 'core', 'relationship': 'x'}]},
                    {'decisions': [{'id': 'A', 'tier': 'same', 'relationship': ''}]},
                    {'decisions': [{'id': 'A', 'tier': 'same', 'relationship': '相似度 90%'}]},
                    {'keep': ['A']}):
            with self.assertRaises(ValueError):
                recall_screen.tiered(bad, self.PACKET)


class SelectionOrderTests(unittest.TestCase):
    def row(self, cid, tier):
        return {'scope': {'candidate_id': cid, 'scenario_id': 'S', 'jurisdiction': 'US', 'right_type': 'design'},
                'tier': tier, 'relationship': cid + ' 关系', 'session': 's', 'mode': 'image',
                'reading_level': 'image_comparison', 'guide': {'included_product_objects': {'PRODUCT': ['D']}},
                'evidence_refs': ['EV-' + cid], 'candidate_content': cid, 'product_content': 'p'}

    def test_same_then_unseen_then_similar_within_the_cap(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            recall_screen.save_kept(root, 'image', [self.row('S1', 'similar'), self.row('U1', 'unseen'),
                                                    self.row('A1', 'same'), self.row('S2', 'similar')])
            recorded = []
            with mock.patch.object(recall_screen, '_pending_scopes',
                                   return_value={('S1', 'S', 'US', 'design'), ('U1', 'S', 'US', 'design'),
                                                 ('A1', 'S', 'US', 'design'), ('S2', 'S', 'US', 'design')}), \
                    mock.patch.object(recall_screen, 'selected_count', return_value=1), \
                    mock.patch.object(precision, 'DESIGN_CAP', 3), \
                    mock.patch.object(recall_screen, '_record_isolating',
                                      side_effect=lambda root, rows, d, s: (recorded.extend(rows) or (len(rows), []))):
                summary = recall_screen.select(root, 'image')
        self.assertEqual(summary['selected'], 2)
        self.assertEqual([(row['candidate_id'], row['decision']) for row in recorded],
                         [('A1', 'selected'), ('U1', 'selected'), ('S1', 'not_selected'), ('S2', 'not_selected')])
        self.assertEqual(recorded[1]['reviewer'], recall_screen.UNSEEN_REVIEWER)
        self.assertEqual(recorded[2]['reviewer'], recall_screen.CAP_REVIEWER)


class InactiveStatusTests(unittest.TestCase):
    def test_a_card_reported_not_active_in_the_us_leaves_by_rule(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            raw = root / 'raw' / 'serpapi_google_patents'
            raw.mkdir(parents=True)
            (raw / 'QRY-1.json').write_text(json.dumps({'organic_results': [
                {'publication_number': 'US20090205580A1', 'country_status': {'US': 'NOT_ACTIVE'}},
                {'publication_number': 'US11401089B2', 'country_status': {'US': 'ACTIVE', 'WO': 'NOT_ACTIVE'}}]}))
            statuses = precision.card_statuses(root)
        dead = precision.inactive_us_status({'publication_number': 'US20090205580A1', 'right_type': 'patent'}, statuses)
        self.assertIn('NOT_ACTIVE', dead)
        self.assertIsNone(precision.inactive_us_status({'publication_number': 'US11401089B2', 'right_type': 'patent'},
                                                       statuses))
        self.assertIsNone(precision.inactive_us_status({'publication_number': 'US99B2', 'right_type': 'patent'}, statuses))
        self.assertIsNone(precision.inactive_us_status({'publication_number': 'EP1A1', 'right_type': 'patent'}, statuses))


class UnseenNameTests(unittest.TestCase):
    def test_specific_names_and_word_for_word_titles(self):
        task = {'query_terms': [{'discovery_problem_id': 'recall-v1:design-names',
                                 'value': '("rolling grill basket" OR "cylindrical grill basket")'},
                                {'discovery_problem_id': 'recall-v1:design-broad', 'value': 'basket AND (grill)'}]}
        names = precision.specific_names(task)
        self.assertEqual(names, ['rolling grill basket', 'cylindrical grill basket'])
        self.assertEqual(precision.title_matches('Rolling grilling basket', names), 'rolling grill basket')
        self.assertIsNone(precision.title_matches('Grill basket', names))
        self.assertIsNone(precision.title_matches('Pet toy', ['cat teaser']))

    def test_the_fallback_keeps_only_the_whole_listing_phrase(self):
        concepts = recall.program_concepts('Butterfly Cat Toy', narrow=True)
        self.assertEqual([row['value'] for row in concepts['article_names']], ['butterfly cat toy'])
        terms = recall.compose_terms(concepts)
        self.assertEqual([row['discovery_problem_id'] for row in terms],
                         ['recall-v1:design-names', 'recall-v1:article-names'])     # no "toy AND (butterfly OR cat)"
        wide = recall.program_concepts('Butterfly Cat Toy')
        self.assertEqual([row['value'] for row in wide['article_names']], ['butterfly cat toy', 'cat toy'])


if __name__ == '__main__':
    unittest.main()


class SmallPieceTests(unittest.TestCase):
    def test_query_reviews_run_at_low_effort(self):
        from report_review_host import native_review_command, with_effort
        command = native_review_command(Path('/x/codex'), None, Path('/w'))
        low = with_effort(command, 'low')
        self.assertIn('model_reasoning_effort="low"', low)
        self.assertNotIn('model_reasoning_effort="low"', command)
        with self.assertRaises(ValueError):
            with_effort(command, 'max')

    def test_finished_batches_keep_no_image_copies(self):
        from text_triage_host import drop_image_copies
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'packet.json').write_text('{}')
            (root / 'M1.png').write_bytes(b'png bytes')
            (root / 'M2.jpg').write_bytes(b'jpg bytes')
            self.assertEqual(drop_image_copies(root), 2)
            self.assertEqual(sorted(p.name for p in root.iterdir()), ['image-copies-removed.json', 'packet.json'])
            manifest = json.loads((root / 'image-copies-removed.json').read_text())
            self.assertEqual([row['name'] for row in manifest['images']], ['M1.png', 'M2.jpg'])

    def test_broad_names_stay_out_of_design_rewrites(self):
        import auto_refine
        task = {'task_id': 'T', 'recall_revision': recall.REVISION, 'candidate_precision_revision': precision.REVISION,
                'query_terms': [{'discovery_problem_id': 'recall-v1:design-names', 'value': '("cat teaser" OR "teaser wand")'},
                                {'discovery_problem_id': 'recall-v1:function-1',
                                 'value': '("cat toy" OR "pet toy" OR "cat teaser") AND (motor OR electric)'}],
                'discovery_semantic_reviews': [{'stage': 'after', 'query_id': 'Q1', 'next_action': 'refine',
                                                'refine_query': {'names': ['cat teaser', 'pet toy', 'cat wand']}}]}
        self.assertEqual(sorted(precision.broad_names(task)), ['cat toy', 'pet toy'])
        term = auto_refine._reviewer_term(task, {'query_id': 'Q1', 'right_type': 'design', 'derived_from': ['product.title']})
        self.assertEqual(term['value'], '("cat teaser" OR "cat wand")')
        only_broad = dict(task, discovery_semantic_reviews=[{'stage': 'after', 'query_id': 'Q1', 'next_action': 'refine',
                                                             'refine_query': {'names': ['pet toy']}}])
        self.assertIsNone(auto_refine._reviewer_term(only_broad, {'query_id': 'Q1', 'right_type': 'design',
                                                                  'derived_from': ['product.title']}))
        patent = auto_refine._reviewer_term(task, {'query_id': 'Q1', 'right_type': 'patent', 'derived_from': ['product.title']})
        self.assertIn('"pet toy"', patent['value'])                  # utility full text keeps the broad names

    def test_lean_module_packets_index_not_selected_records(self):
        import module_review
        source = {'task': {'candidate_precision_revision': precision.REVISION},
                  'candidates': {'patents': [{'candidate_id': 'C1', 'right_type': 'design'},
                                             {'candidate_id': 'C2', 'right_type': 'design'}]},
                  'evidence': {'collections': {'sources': [
                      {'evidence_id': 'EV-1', 'source_run_id': 'ATT-1', 'payload': {'candidate_id': 'C1'}},
                      {'evidence_id': 'EV-2', 'source_run_id': 'ATT-2', 'payload': {'candidate_id': 'C2'}},
                      {'evidence_id': 'EV-3', 'source_run_id': 'ATT-3'}]}}}
        packet = {'task': {'specialty_analysis_events': [
                      {'kind': 'fact', 'right_type': 'patent',
                       'review_packet_stub': {'revision': module_review.PACKET_SCOPE_REVISION}},
                      {'kind': 'fact', 'right_type': 'design'}]},
                  'evidence': {'collections': {'sources': [
                      {'evidence_id': 'EV-1', 'review_packet_stub': {'revision': 'x'}},
                      {'evidence_id': 'EV-2'}, {'evidence_id': 'EV-3'}]},
                      'source_runs': [{'run_id': 'ATT-1'}, {'run_id': 'ATT-2'}, {'run_id': 'ATT-3'}]}}
        with mock.patch.object(module_review, 'triage_partition',
                               return_value=({'C1': {'decision': 'not_selected', 'reason': 'r'}}, set(), {})):
            module_review.lean_diet(packet, source)
        self.assertEqual([row['evidence_id'] for row in packet['evidence']['collections']['sources']], ['EV-2', 'EV-3'])
        self.assertEqual([row['run_id'] for row in packet['evidence']['source_runs']], ['ATT-2', 'ATT-3'])
        self.assertEqual(len(packet['task']['specialty_analysis_events']), 1)
        diet = packet['review_packet_diet']
        self.assertEqual((diet['not_selected_evidence_index'], diet['not_selected_runs_left_out'],
                          diet['other_module_event_stubs_left_out']), ({'C1': ['EV-1']}, 1, 1))
