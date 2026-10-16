"""Program default triage: same-product cards and identity-less web cards, recorded through the ordinary recorder."""
import unittest

from common import atomic_write_json, load_json
from test_text_triage_host import TextHostFixture

LONG = 'Learn about securing licenses and ensuring compliance with music copyright when you post cover songs online.'


def card(cid, *, title, snippet=LONG, url='https://example.org/page', nature='web_result', image=''):
    return {'candidate_id': cid, 'jurisdiction': 'US', 'right_type': 'unknown', 'candidate_nature': nature,
            'source': 'serper_web', 'source_index': 'google_search', 'title': title, 'snippet': snippet, 'url': url,
            'image_url': image, 'thumbnail_url': image, 'evidence_refs': ['EV-' + cid],
            'sources': [{'evidence_id': 'EV-' + cid, 'provider': 'serper_web'}]}


CARDS = [
    card('W0', title='Post Cover Songs LEGALLY on YouTube'),                                     # web card
    card('W1', title='Acme Folding Stand hinged support for phones at Example Store',
         snippet='Buy the Acme Folding Stand.', url='https://store.example/acme-folding-stand'),    # same product
    card('W2', title='Acme Folding Stand patent lawsuit filed', snippet=LONG),                    # enforcement: kept
    card('W3', title='Phone holder', snippet='short'),                                           # too little text
    card('W4', title='Folding stand at Example', snippet='Listing B000000002 image',
         url='https://shop.example/dp/B000000002', nature='visual_match', image='https://img.example/a.jpg'),
    card('W5', title='Ministrap v. Best Buy secure strap litigation case summary', snippet=LONG),  # case pattern
]


class TriageDefaultsTests(TextHostFixture):
    def extra_enforcement(self):
        evidence = [{'evidence_id': 'EV-' + row['candidate_id'], 'provider': 'serper_web',
                     'collected_at': '2026-10-01T00:00:00Z', 'payload': {'title': row['title']}} for row in CARDS]
        return evidence, [dict(row) for row in CARDS]

    def setUp(self):
        super().setUp()
        task = load_json(self.root / 'task.json')
        task['assessment_revision'] = 'known-findings-risk-v1'
        task['best_estimate_revision'] = 'best-estimate-risk-v2'
        task['product'].update(brand='Acme', title='Folding Stand with a hinged support arm', requested_asin='B000000002')
        atomic_write_json(self.root / 'task.json', task)

    def annotations(self):
        return load_json(self.root / 'materiality-annotations.json')['annotations']

    def test_rules_pick_only_public_cards_without_identity(self):
        import triage_defaults
        result = triage_defaults.run(self.root, dry_run=True)
        self.assertEqual(sorted(result['candidates']), ['W0', 'W1', 'W4'])
        self.assertEqual(result['by_rule'], {'web_card': 1, 'same_product': 2})

    def test_decisions_pass_the_ordinary_recorder_with_program_reviewer(self):
        import triage_defaults
        outcome = triage_defaults.run(self.root)
        self.assertEqual((outcome['recorded'], outcome['rejected']), (3, []))
        rows = {row['candidate_id']: row for row in self.annotations() if row['candidate_id'].startswith('W')}
        self.assertEqual(set(rows), {'W0', 'W1', 'W4'})
        for row in rows.values():
            self.assertEqual((row['decision'], row['reviewer'], row['reading_level']),
                             ('not_selected', 'program:triage-defaults', 'result_record'))
            self.assertTrue(row['comparison']['difference'] and row['comparison']['applicability_limit'])
            self.assertIn('right_type', row['candidate_relation']['identity_gaps'])
        self.assertEqual(rows['W1']['reason'], triage_defaults.SAME_PRODUCT_REASON)
        # re-running finds nothing left to decide
        self.assertEqual(triage_defaults.run(self.root, dry_run=True)['would_record'], 0)

    def test_typed_candidates_are_never_touched(self):
        import triage_defaults
        identity = triage_defaults.product_identity(load_json(self.root / 'task.json'))
        typed = {**CARDS[0], 'right_type': 'patent'}
        numbered = {**CARDS[0], 'publication_number': 'US1234567B2'}
        self.assertIsNone(triage_defaults.rule_for(typed, identity))
        self.assertIsNone(triage_defaults.rule_for(numbered, identity))

    def test_older_tasks_are_refused(self):
        import triage_defaults
        task = load_json(self.root / 'task.json')
        task['best_estimate_revision'] = 'best-estimate-risk-v1'
        atomic_write_json(self.root / 'task.json', task)
        with self.assertRaisesRegex(ValueError, 'TRIAGE_DEFAULTS_REQUIRE_BEST_ESTIMATE_V2'):
            triage_defaults.run(self.root, dry_run=True)

    def test_stem_and_identity_helpers(self):
        import triage_defaults
        self.assertEqual(triage_defaults._stem('Lid Latch the reusable universal lid securing strap'), 'lid latch')
        identity = triage_defaults.product_identity({'product': {
            'brand': 'Mella', 'title': 'Lid Latch the reusable universal lid securing strap for crockpots',
            'requested_asin': 'B07HQL3SPZ'}})
        lowes = {'candidate_nature': 'visual_match', 'right_type': 'unknown',
                 'title': 'Mella Lid Latch the reusable universal lid securing strap at Lowes.com',
                 'url': 'https://www.lowes.com/pd/Mella-Lid-Latch/7987118'}
        amazon = {'candidate_nature': 'visual_match', 'right_type': 'unknown',
                  'title': 'Amazon.com: Lid Latch the reusable universal lid securing strap for crockpots, casserole',
                  'url': 'https://www.amazon.com/Lid-Latch/dp/B07HQL3SPZ'}
        self.assertEqual(triage_defaults.rule_for(lowes, identity), 'same_product')
        self.assertEqual(triage_defaults.rule_for(amazon, identity), 'same_product')


if __name__ == '__main__':
    unittest.main()
