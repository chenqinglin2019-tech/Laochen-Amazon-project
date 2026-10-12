import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import consumer_voice_local_reprocess as local
import consumer_all_history_report as report
import consumer_voice_evidence as evidence


def voice(index, kind=None, status=None, code='charging'):
    need = {'code': code, 'label': '无线充电与供电', 'quote': 'I need charging',
            'kano_reason': '充电是该作者选购前提' if kind else '只描述存在充电，未说明满足与否的价值',
            'kano_review_version': '1.0.0', 'kano_review_status': status or ('classified' if kind else 'insufficient')}
    if kind:
        need['kano_type'] = kind
    return {'voice_id': str(index), 'hard_identity': 'source:' + str(index), 'coding_method': 'agent_reviewed',
            'platform': 'youtube', 'author_key': None, 'thread_key': 'video-one', 'excerpt': 'I need charging',
            'needs': [need], 'topic_codes': [code], 'semantic_codes': []}


class KanoTests(unittest.TestCase):
    def test_majority_does_not_replace_support_count_with_related_total(self):
        rows = [voice(i, kind) for i, kind in enumerate(['必备型']*3 + ['期望型','魅力型'] + [None]*86)]
        items, audit = local._kano_results(rows, 1072)
        self.assertEqual(1, len(items))
        item = items[0]
        self.assertEqual(('必备型', 91, 5, 3, .6), (item['kano_type'], item['related_count'], item['classified_count'], item['count'], item['dominant_share']))
        self.assertEqual(round(3/1072, 6), item['share'])
        self.assertEqual(round(91/1072, 6), item['related_share'])
        self.assertEqual(86, audit[0]['review_counts']['insufficient'])
        html = report._render_kano({'kano': items})
        self.assertEqual(1, html.count('class="kano-item '))
        self.assertIn('相关声音：91', html)
        self.assertIn('主导类型依据：3 条 / 可分类 5 条', html)
        self.assertIn('60.0%', html)
        self.assertIn('充电是该作者选购前提', html)

    def test_relative_plurality_can_be_below_half(self):
        rows = [voice(i, k) for i, k in enumerate(['必备型']*4 + ['期望型']*3 + ['魅力型']*3)]
        self.assertEqual(.4, local._kano(rows, 10)[0]['dominant_share'])

    def test_tie_and_zero_classification_do_not_force_a_type(self):
        items, audit = local._kano_results([voice(1, '必备型'), voice(2, '期望型')], 2)
        self.assertEqual([], items)
        self.assertEqual('tie', audit[0]['decision'])
        items, audit = local._kano_results([voice(3)], 1)
        self.assertEqual([], items)
        self.assertEqual('unclassified', audit[0]['decision'])
        self.assertEqual(([], []), local._kano_results([], 0))

    def test_same_underlying_comment_votes_once_different_comments_survive(self):
        one = voice(1, '必备型')
        rows = [one, copy.deepcopy(one), voice(2, '必备型')]
        item = local._kano(rows, 2)[0]
        self.assertEqual(2, item['count'])
        self.assertEqual(0, item['known_authors'])
        bad = copy.deepcopy(one)
        bad['needs'][0]['kano_type'] = '反向型'
        with self.assertRaises(local.LocalReprocessError):
            local._kano([one, bad], 1)

    def test_old_cache_or_conflicting_expression_does_not_vote(self):
        old = voice(1, '必备型')
        old['needs'][0].pop('kano_review_version')
        old['needs'][0].pop('kano_review_status')
        items, audit = local._kano_results([old, voice(2, status='conflict')], 2)
        self.assertEqual([], items)
        self.assertEqual(1, audit[0]['review_counts']['unreviewed'])
        self.assertEqual(1, audit[0]['review_counts']['conflict'])

    def test_invalid_review_state_cannot_enter_aggregation(self):
        for patch in [
            {'kano_review_status': 'insufficient', 'kano_type': '必备型'},
            {'kano_review_status': 'insufficient', 'kano_type': 'invalid'},
            {'kano_review_status': 'classified', 'kano_type': None},
            {'kano_review_status': 'conflict', 'kano_reason': ''},
            {'kano_review_status': 'classified', 'kano_review_version': None},
        ]:
            row = voice(1)
            row['needs'][0].update(patch)
            with self.subTest(patch=patch), self.assertRaises(local.LocalReprocessError):
                local._kano_results([row], 1)

    def test_stale_explicit_review_is_readable_but_requires_recheck_before_import(self):
        row = voice(1, '必备型')
        row['needs'][0]['kano_review_version'] = '0.9.0'
        items, audit = local._kano_results([row], 1)
        self.assertEqual([], items)
        self.assertEqual(1, audit[0]['review_counts']['unreviewed'])
        with self.assertRaises(evidence.EvidenceError):
            evidence.validate_kano_review(row['needs'][0])

    def test_need_specific_classification_does_not_spread_to_co_mentions(self):
        row = voice(1, '反向型', code='magnet')
        row['needs'].append(voice(2, code='charging')['needs'][0])
        items, audit = local._kano_results([row], 1)
        self.assertEqual(['magnet'], [i['need_code'] for i in items])
        self.assertEqual(2, len(audit))

    def test_general_satisfaction_is_not_a_product_attribute(self):
        row = voice(1, '必备型', code='general_satisfaction')
        with self.assertRaises(local.LocalReprocessError):
            local._kano_results([row], 1)
        row['needs'][0].pop('kano_type')
        row['needs'][0]['kano_review_status'] = 'insufficient'
        items, audit = local._kano_results([row], 1)
        self.assertEqual([], items)
        self.assertEqual(1, audit[0]['related_count'])

    def test_explicit_empty_results_never_revive_category_history(self):
        historical = {'need_code': 'charging', 'need': '充电', 'kano_type': '必备型', 'count': 3}
        self.assertNotIn('class="kano-item ', report._render_kano({'kano': [], 'category_summary': {'kano': [historical]}}))

    def test_prior_product_mapping_uses_only_current_winner_once(self):
        old = [{'need_code': 'wireless_charging', 'classification': '必备型', 'count': 99},
               {'need_code': 'charging', 'classification': '魅力型'}]
        self.assertEqual([], local._prior_kano_mapping(old, []))
        current = [{'need_code': 'charging', 'need': '充电', 'kano_type': '反向型', 'rationale': '明确拒绝无线'}]
        rows = local._prior_kano_mapping(old, current)
        self.assertEqual(1, len(rows))
        self.assertEqual('反向型', rows[0]['classification'])
        self.assertEqual('明确拒绝无线', rows[0]['design_response'])
        self.assertNotIn('count', rows[0])

    def test_legacy_renderer_collapses_duplicates_and_reads_rationales(self):
        rows = [{'need_code': 'charging', 'need': '充电', 'kano_type': k, 'count': n, 'share': n/100,
                 'rationales': ['原文明确需要充电']} for k,n in [('必备型',3),('魅力型',1),('期望型',1)]]
        html = report._render_kano({'kano': rows})
        self.assertEqual(1, html.count('class="kano-item '))
        self.assertIn('原文明确需要充电', html)
        self.assertNotIn('相关声音：', html)
        rows[1]['count'] = 3
        self.assertNotIn('class="kano-item ', report._render_kano({'kano': rows}))

if __name__ == '__main__':
    unittest.main()
