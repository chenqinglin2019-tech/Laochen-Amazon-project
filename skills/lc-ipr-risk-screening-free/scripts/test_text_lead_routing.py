"""Public web leads without an image are judged from their card text, not handed to a picture session."""
import unittest

from common import atomic_write_json, load_json
from test_text_triage_host import TextHostFixture

LEAD_SNIPPET = 'Replacement lid latch assembly for a washing machine; fits several older part numbers.'


def web_lead(number, *, image=''):
    return {'candidate_id': 'W%d' % number, 'jurisdiction': 'US', 'right_type': 'unknown',
            'candidate_nature': 'web_result', 'source': 'serper_web', 'source_index': 'google_search',
            'title': 'Synthetic web result %d' % number, 'snippet': LEAD_SNIPPET, 'url': 'https://example.org/%d' % number,
            'image_url': image, 'thumbnail_url': '', 'evidence_refs': ['EV-W%d' % number],
            'sources': [{'evidence_id': 'EV-W%d' % number, 'provider': 'serper_web'}]}


class TextLeadRoutingTests(TextHostFixture):
    """Reuses the scoped real-task fixture; only adds two enforcement web leads to it."""

    def extra_enforcement(self):
        evidence, candidates = [], []
        for number, image in ((0, ''), (1, 'https://example.org/thumb.png')):
            evidence.append({'evidence_id': 'EV-W%d' % number, 'provider': 'serper_web',
                             'collected_at': '2026-10-01T00:00:00Z',
                             'payload': {'title': 'Synthetic web result %d' % number}})
            candidates.append(web_lead(number, image=image))
        return evidence, candidates

    def lead_entries(self, entries):
        return [e for e in entries if e.get('candidate_id', '').startswith('W')]

    def test_predicate_is_exact(self):
        from host_triage import text_only_lead
        self.assertTrue(text_only_lead(web_lead(0)))
        self.assertFalse(text_only_lead(web_lead(1, image='https://example.org/a.png')))
        self.assertFalse(text_only_lead({**web_lead(0), 'candidate_nature': 'visual_match'}))
        self.assertFalse(text_only_lead({**web_lead(0), 'right_type': 'design'}))
        self.assertFalse(text_only_lead(None))

    def test_only_the_imageless_lead_goes_to_the_text_host_and_the_visual_host_leaves_it(self):
        import text_triage_host
        import visual_triage_host
        from host_triage import text_only_candidate_ids
        self.assertEqual(text_only_candidate_ids(self.root), {'W0'})
        text = {e['candidate_id'] for e in text_triage_host.pending_entries(self.root)}
        visual = {e['candidate_id'] for e in visual_triage_host.pending_entries(self.root)}
        self.assertIn('W0', text)
        self.assertNotIn('W1', text)
        self.assertNotIn('W0', visual)
        self.assertEqual(text & visual, set())

    def test_action_cards_point_each_lead_at_the_host_that_will_actually_take_it(self):
        import advance_work
        import text_triage_host
        import visual_triage_host
        from workflow_v24 import work_view_from_dir
        entries = {e['candidate_id']: e for e in work_view_from_dir(self.root)['entries']
                   if e.get('kind') == 'triage' and e.get('candidate_id') in {'W0', 'W1'}}
        self.assertEqual(set(entries), {'W0', 'W1'})
        imageless = advance_work.action_card(self.root, entries['W0'])
        with_image = advance_work.action_card(self.root, entries['W1'])
        self.assertIn('batch_text_triage', imageless)
        self.assertNotIn('batch_visual_triage', imageless)
        self.assertIn('batch_visual_triage', with_image)
        self.assertNotIn('batch_text_triage', with_image)
        # a card never names a host that would skip the candidate
        self.assertIn('W0', {e['candidate_id'] for e in text_triage_host.pending_entries(self.root)})
        self.assertNotIn('W0', {e['candidate_id'] for e in visual_triage_host.pending_entries(self.root)})
        self.assertIn('W1', {e['candidate_id'] for e in visual_triage_host.pending_entries(self.root)})

    def test_visual_host_keeps_every_unknown_lead_for_a_task_without_the_host_family(self):
        import visual_triage_host
        task = load_json(self.root / 'task.json')
        task.pop('host_triage_revision', None)
        task.pop('host_triage', None)
        atomic_write_json(self.root / 'task.json', task)
        self.assertEqual(visual_triage_host.compact_enabled(task), False)
        # legacy behaviour: nothing is diverted away from the visual host
        from unittest.mock import patch
        with patch('host_triage.text_only_candidate_ids', side_effect=AssertionError('must not be consulted')):
            visual_triage_host.pending_entries(self.root)

    def test_text_packet_and_recording_for_an_unknown_right_lead(self):
        import text_triage_host
        entries = self.lead_entries(self.entries())
        self.assertTrue(entries, 'the imageless web lead must be pending for the text host')
        packet, images = text_triage_host.prepare_packet(self.root, [e for e in entries if e['candidate_id'] == 'W0'])
        self.assertEqual(images, {})
        unit = packet['units'][0]
        self.assertEqual(unit['template']['right_type'], 'unknown')
        self.assertTrue(unit['exclusion_allowed'])               # 40+ characters of snippet
        self.assertEqual(unit['reading_level'], 'result_record')
        self.assertIn('right_type', unit['guide'].get('identity_gaps_prefilled_are_the_minimum', []))
        raw = {'decisions': [{'unit_id': unit['unit_id'], 'decision': 'not_selected',
                              'relationship': 'The card describes a washing machine lid latch part, unrelated to the product.',
                              'difference': 'The card concerns a household appliance repair part; the product is a flexible band.'}]}
        directory = self.root / 'commit-web'
        directory.mkdir()
        outcome = text_triage_host.commit(self.root, [e for e in entries if e['candidate_id'] == 'W0'],
                                          packet, raw, 'synthetic', directory)
        self.assertEqual(outcome, {'recorded': 1, 'rejected': []})
        row = [r for r in self.annotations() if r['candidate_id'] == 'W0'][0]
        self.assertEqual((row['decision'], row['right_type'], row['reviewer']), ('not_selected', 'unknown', 'native-text-synthetic'))
        self.assertIn('right_type', row['candidate_relation']['identity_gaps'])
        self.assertFalse([e for e in self.lead_entries(text_triage_host.pending_entries(self.root))
                          if e['candidate_id'] == 'W0'])

    def test_a_title_only_lead_can_never_be_excluded(self):
        import text_triage_host
        candidates = load_json(self.root / 'normalized-candidates.json')
        for row in candidates['enforcement']:
            if row['candidate_id'] == 'W0':
                row['snippet'] = ''
        atomic_write_json(self.root / 'normalized-candidates.json', candidates)
        entries = [e for e in self.lead_entries(self.entries()) if e['candidate_id'] == 'W0']
        packet, _ = text_triage_host.prepare_packet(self.root, entries)
        self.assertFalse(packet['units'][0]['exclusion_allowed'])
        raw = {'decisions': [{'unit_id': packet['units'][0]['unit_id'], 'decision': 'not_selected',
                              'relationship': 'Looks unrelated', 'difference': 'Different thing'}]}
        with self.assertRaisesRegex(ValueError, 'TEXT_INSUFFICIENT_CARD_CANNOT_EXCLUDE'):
            text_triage_host.decisions_from_output(raw, packet, 'synthetic')


if __name__ == '__main__':
    unittest.main()
