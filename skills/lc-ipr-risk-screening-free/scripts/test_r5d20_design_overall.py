"""r5d20 (owner decision 2026-10-14): US design patents compared, screened and graded main body first.

Owner's B0H16FDSD8 run: USD1035381S1 "Rolling grilling basket" (a cylindrical mesh basket with mesh end faces and a
separately drawn fork) was marked differs in all nine views - every view also showed the fork or the mesh ends - and
the pre-review screen removed it; a slightly tapered cylindrical basket design (USD1055634S1) was rated 低 by both
chains. These tests pin the main-body method, the screen v2 rule and the chief-draft floor; tasks without
``design_assessment_revision`` keep every old behaviour.
"""
import unittest
from copy import deepcopy
from unittest import mock

import comparison_host as ch
import design_overall as do
import design_screen as ds
import prepare_adjudication as pa

TASK = {'design_assessment_revision': do.REVISION}
UNIT = {'unit_id': 'CMP-1', 'kind': 'design', 'candidate_id': 'CAND-1', 'scenario_id': 'product_entry',
        'jurisdiction': 'US', 'right_type': 'design', 'intake_event_id': 'I-1', 'claims_material_event_id': 'M-1',
        'document_version': 'v', 'claims_evidence_ref': 'EV-REC', 'product_evidence_ref': 'EV-PROD',
        'publication_number': 'USD1035381S1', 'title': 'Rolling grilling basket', 'design_claim': 'claim',
        'listed_views': 2, 'views': [{'view_id': 'D00000', 'attachment': 'a.png', 'evidence_id': 'EV-D0'},
                                     {'view_id': 'D00001', 'attachment': 'b.png', 'evidence_id': 'EV-D1'}]}
SAME_FORM = {'design': '细长圆筒网篮，两端宽环边', 'product': '细长圆筒网篮，两端圆形端缘', 'relation': 'same_form',
             'reasoning': '两者都是细长圆筒形网格篮体，第一眼是同一种造型。'}


def answer(**extra):
    row = {'unit_id': 'CMP-1', 'product_state': '组装展示状态',
           'views': [{'view_id': 'D00000', 'result': 'corresponds', 'reasoning': '主体圆筒网篮一致',
                      'right_location': '篮体', 'product_location': '篮体', 'image_ids': ['IMG-001']},
                     {'view_id': 'D00001', 'result': 'corresponds', 'reasoning': '主体一致，端面不同',
                      'right_location': '端面', 'product_location': '端盖', 'image_ids': ['IMG-001']}],
           'design_scope_parts': [{'part_id': 'basket_body', 'description': '圆筒网篮', 'treatment': 'claimed',
                                   'interpretation_basis': '实线'}],
           'overall_visual_relationship': '主体造型相同，端面与附件不同', 'similarities': [], 'differences': [],
           'unknowns': [], 'perspective_limitations': '斜视图', 'assumptions': [], 'lower_if': []}
    row.update(extra)
    return row


NEW = {'article_relation': 'same_article', 'main_body': SAME_FORM,
       'secondary_differences': [{'part': '端面', 'design_feature': '网格端面', 'product_feature': '实心端板',
                                  'prominence': 'noticeable'},
                                 {'part': '附件', 'design_feature': '分开画的双叉工具', 'product_feature': '环柄弯钩',
                                  'prominence': 'minor'}]}


class ComparisonTests(unittest.TestCase):
    def test_new_method_requires_and_records_the_main_body(self):
        packet = {'units': [UNIT], 'product_images': [{'image_id': 'IMG-001', 'attachment': 'p.jpg'}],
                  'design_method': do.REVISION, 'product': {}, 'product_fact': '', 'schema': 'S'}
        self.assertIn('先看主体、再看细节', ch.prompt(packet))
        with self.assertRaisesRegex(ValueError, 'COMPARISON_DESIGN_MAIN_BODY_REQUIRED'):
            ch.decisions_from_output({'units': [answer()]}, packet, 'S1')
        bad = dict(NEW, main_body=dict(SAME_FORM, relation='identical'))
        with self.assertRaisesRegex(ValueError, 'COMPARISON_DESIGN_MAIN_BODY_INVALID'):
            ch.decisions_from_output({'units': [answer(**bad)]}, packet, 'S1')
        with self.assertRaisesRegex(ValueError, 'COMPARISON_DESIGN_SECONDARY_INVALID'):
            ch.decisions_from_output({'units': [answer(**dict(NEW, secondary_differences=[{'part': 'x'}]))]}, packet, 'S1')
        decision = ch.decisions_from_output({'units': [answer(**NEW)]}, packet, 'S1')[0]
        request = ch.transaction_request(decision, 'native-comparison-S1')
        close = request['events'][-1]['comparison']
        self.assertEqual((close['design_method'], close['article_relation'], close['main_body']['relation']),
                         (do.REVISION, 'same_article', 'same_form'))
        self.assertEqual(len(close['secondary_differences']), 2)
        self.assertIn('主体造型相同', close['reasoning'])
        self.assertIn('端面（一眼可见）', close['reasoning'])

    def test_old_packets_keep_the_view_by_view_prompt_and_record(self):
        packet = {'units': [UNIT], 'product_images': [{'image_id': 'IMG-001', 'attachment': 'p.jpg'}],
                  'product': {}, 'product_fact': '', 'schema': 'S'}
        self.assertIn(ch.DESIGN_PROMPT, ch.prompt(packet))
        decision = ch.decisions_from_output({'units': [answer()]}, packet, 'S1')[0]
        self.assertNotIn('main_body_fields', decision)
        close = ch.transaction_request(decision, 'native-comparison-S1')['events'][-1]['comparison']
        self.assertNotIn('main_body', close)
        self.assertTrue(close['reasoning'].startswith('组装展示状态：授权附图逐幅比较'))


class ScreenTests(unittest.TestCase):
    PACKET = {'schema': 'IPR-DESIGN-SCREEN/1.0', 'product': {}, 'objects': [],
              'units': [{'unit_id': 'DSC-1', 'publication_number': 'USD968891S1', 'title': 'Grilling basket',
                         'design_claim': 'claim', 'views': [{'view_id': 'D00000', 'attachment': 'a.png'},
                                                            {'view_id': 'D00001', 'attachment': 'b.png'}]}],
              'product_images': [{'image_id': 'IMG-001', 'attachment': 'p.jpg'}], 'screen_method': do.REVISION}
    EXCLUDE = {'unit_id': 'DSC-1', 'decision': 'exclude', 'relationship': '扁平夹篮对圆筒篮', 'difference': '主体形状不同',
               'differences': [{'view_id': 'D00000', 'image_ids': ['IMG-001'], 'design_feature': '扁平矩形双片网架',
                                'product_feature': '圆筒网篮'},
                               {'view_id': 'D00001', 'image_ids': ['IMG-001'], 'design_feature': '三角形轮廓',
                                'product_feature': '圆形端面'}]}

    def test_b_states_both_main_forms_and_only_a_different_form_excludes(self):
        self.assertIn('主体造型是不是同一种', ds.prompt(self.PACKET))
        with self.assertRaisesRegex(ValueError, 'DESIGN_SCREEN_MAIN_FORM_REQUIRED'):
            ds.decisions_from_output({'decisions': [self.EXCLUDE]}, self.PACKET, 'S1')
        forms = {'design_main_form': '扁平矩形夹篮', 'product_main_form': '圆筒网篮'}
        same = ds.decisions_from_output({'decisions': [dict(self.EXCLUDE, **forms, main_form_relation='same_form')]},
                                        self.PACKET, 'S1')[0]
        self.assertEqual((same['decision'], same['coerced']), ('keep', 'exclude_without_different_form'))
        different = ds.decisions_from_output({'decisions': [dict(self.EXCLUDE, **forms, main_form_relation='different_form')]},
                                             self.PACKET, 'S1')[0]
        self.assertEqual((different['decision'], different['main_form_relation']), ('exclude', 'different_form'))

    def test_old_packets_keep_the_overall_impression_prompt(self):
        packet = {k: v for k, v in self.PACKET.items() if k != 'screen_method'}
        self.assertIn('两者的整体视觉印象是否明显不同', ds.prompt(packet))
        self.assertEqual(ds.decisions_from_output({'decisions': [self.EXCLUDE]}, packet, 'S1')[0]['decision'], 'exclude')

    def _verdict(self, task, close):
        inventory = {'kind': 'inventory', 'event_id': 'INV-1', 'reviewer': 'native-comparison-S1', 'intake_event_id': 'I-1',
                     'units': [{'kind': 'design', 'necessary_views': ['D00000', 'D00001']}]}
        close = {'kind': 'comparison', 'unit_id': 'design', 'inventory_event_id': 'INV-1', 'intake_event_id': 'I-1',
                 'disposition': 'compared', 'views': [{'view_id': 'D00000', 'result': 'differs'},
                                                      {'view_id': 'D00001', 'result': 'differs'}], **close}
        import specialty_analysis as sa
        with mock.patch.object(sa, '_intake', return_value={'event_id': 'I-1'}), \
                mock.patch.object(sa, 'events', return_value=[inventory, close]), \
                mock.patch.object(sa, '_scope', side_effect=lambda row: ('CAND-1', 'product_entry', 'US', 'design')):
            return ds.comparison_verdict(task, {'candidate_id': 'CAND-1', 'scenario_id': 'product_entry',
                                                'jurisdiction': 'US', 'right_type': 'design'})

    def test_a_reads_the_main_body_relation_instead_of_counting_views(self):
        # every view differs (the fork, the mesh ends) but the main body is the same form: keep
        verdict = self._verdict(TASK, {'design_method': do.REVISION, 'article_relation': 'same_article',
                                       'main_body': SAME_FORM})
        self.assertEqual((verdict['exclude'], verdict['reason']), (False, 'main_body_same_form'))
        verdict = self._verdict(TASK, {'design_method': do.REVISION, 'article_relation': 'same_article',
                                       'main_body': dict(SAME_FORM, relation='different_form')})
        self.assertTrue(verdict['exclude'])
        self.assertEqual(self._verdict(TASK, {})['reason'], 'main_body_missing')
        # an old task still counts views
        self.assertTrue(self._verdict({}, {})['exclude'])


class ReviewRuleTests(unittest.TestCase):
    def test_appearance_module_gets_the_main_body_rule_and_criteria(self):
        from report_review_host import review_prompt, CANDIDATE_BINDING_RULE
        task = {'assessment_scenarios': [], 'design_assessment_revision': do.REVISION, 'pipeline_robust_revision': 'robust-v1'}
        design = review_prompt({'task': task, 'module_scope': {'right_types': ['design', 'unregistered_design'],
                                                               'required_scopes': []}, 'candidate_counter_refs': {}}, 1)
        self.assertIn('外观设计评级方法（design-overall-v1', design)
        self.assertIn('主体造型相同（same_form）', design)
        self.assertIn('main_body_form（主体造型关系）', design)
        self.assertNotIn(do.VIEW_CLAUSE, design)
        technical = review_prompt({'task': task, 'module_scope': {'right_types': ['patent', 'utility_model'],
                                                                  'required_scopes': []}}, 1)
        self.assertNotIn('外观设计评级方法', technical)
        old = review_prompt({'task': dict(task, design_assessment_revision=None),
                             'module_scope': {'right_types': ['design'], 'required_scopes': []},
                             'candidate_counter_refs': {}}, 1)
        self.assertNotIn('外观设计评级方法', old)
        self.assertIn(do.VIEW_CLAUSE, old)
        self.assertIn(do.VIEW_CLAUSE, CANDIDATE_BINDING_RULE)


class FloorTests(unittest.TestCase):
    SCOPE = {'candidate_id': 'CAND-1', 'scenario_id': 'product_entry', 'jurisdiction': 'US', 'right_type': 'design'}

    def close(self, relation='same_form', article='same_article', method=do.REVISION):
        return {'event_id': 'CMP-EV', 'reviewer': 'native-comparison-S1', 'design_method': method,
                'article_relation': article, 'main_body': dict(SAME_FORM, relation=relation),
                'secondary_differences': NEW['secondary_differences'], 'evidence_refs': ['EV-REC', 'EV-PROD']}

    def floor(self, close, screen=None, task=TASK):
        with mock.patch.object(do, 'latest_comparison', return_value=close), \
                mock.patch.object(do, 'screen_relation', return_value=screen):
            return do.floor(task, None, self.SCOPE)

    def test_floor_levels(self):
        self.assertEqual(self.floor(self.close())[0], '高')
        # r5d21 owner decision: a similar main body has no program floor (the reviews decide), same_form keeps 高
        self.assertIsNone(self.floor(self.close('similar_form_prominent_difference'))[0])
        self.assertIsNone(self.floor(self.close('different_form'))[0])
        self.assertIsNone(self.floor(self.close(article='different_article'))[0])
        self.assertIsNone(self.floor(self.close(method=None))[0])
        self.assertIsNone(self.floor(None)[0])
        self.assertIsNone(self.floor(self.close(), screen='similar_form_prominent_difference')[0])
        self.assertIsNone(self.floor(self.close(), screen='different_form')[0])
        self.assertIsNone(self.floor(self.close(), task={})[0])

    def row(self, risk, **extra):
        return {'scenario_id': 'product_entry', 'jurisdiction': 'US', 'right_type': 'design', 'candidate_id': 'CAND-1',
                'assessment_object': 'product', 'risk': risk, 'assessment_status': 'assessed', 'reasoning': '端面不同，低风险',
                'evidence_refs': ['EV-REC'], 'counter_evidence': [{'reasoning': '端面不同', 'evidence_refs': ['EV-REC']}],
                'evidence_confidence': '中', **extra}

    def settle(self, left, right, decisions=(), task=TASK, level='高'):
        key = tuple(left.get(name) for name in pa.UNIT_KEYS)
        decisions, worksheet = [deepcopy(row) for row in decisions], []
        basis = {'comparison_event_id': 'CMP-EV', 'relation': 'same_form' if level == '高' else
                 'similar_form_prominent_difference', 'article_relation': 'same_article', 'main_body': SAME_FORM,
                 'secondary_differences': NEW['secondary_differences'], 'evidence_refs': ['EV-REC', 'EV-PROD']}
        with mock.patch.object(do, 'floor', return_value=(level, basis)):
            pa._auto_complete(dict(task, best_estimate_revision='best-estimate-risk-v2'), {}, decisions,
                              {key: left}, {key: right}, {'first': 'A', 'second': 'B'}, worksheet)
        return decisions, worksheet

    def test_both_reviews_below_the_floor_are_lifted_with_the_reason(self):
        decisions, worksheet = self.settle(self.row('低'), self.row('低'))
        self.assertEqual(len(decisions), 1)
        row = decisions[0]
        self.assertEqual((row['risk'], row['assessment_status'], row['evidence_confidence']), ('高', 'assessed', '中'))
        self.assertIn('按外观评级规则定为高', row['reasoning'])
        self.assertIn('两审原评低／低', row['reasoning']); self.assertIn('两审原理由：', row['reasoning'])
        self.assertEqual(row['supporting_evidence'][0]['evidence_refs'], ['EV-REC'])
        self.assertIn('按外观评级规则（design-overall-v1）', row['adjudication_reasoning'])
        self.assertEqual(worksheet[-1]['program_resolution'], do.FLOOR_RESOLUTION)

    def test_a_review_at_the_floor_settles_and_a_higher_split_stays_open(self):
        decisions, _ = self.settle(self.row('低'), self.row('高'), decisions=[dict(self.row('低'), adjudication_reasoning='')])
        self.assertEqual(decisions[0]['risk'], '高')
        decisions, worksheet = self.settle(self.row('中'), self.row('极高'),
                                           decisions=[dict(self.row('中'), adjudication_reasoning='')])
        self.assertEqual(decisions[0]['adjudication_reasoning'], '')
        self.assertEqual(worksheet[-1]['program_resolution'], 'design_floor_open')

    def test_the_scope_row_is_then_decided_by_the_lifted_candidate(self):
        candidate = self.row('低', title='USD1055634S1：Grilling basket')
        scope = dict(self.row('低'), candidate_id=None, reasoning='有界检索支持低风险预判')
        keys = [tuple(row.get(name) for name in pa.UNIT_KEYS) for row in (candidate, scope)]
        decisions, worksheet = [], []
        basis = {'comparison_event_id': 'CMP-EV', 'relation': 'same_form', 'article_relation': 'same_article',
                 'main_body': SAME_FORM, 'secondary_differences': [], 'evidence_refs': ['EV-REC']}
        with mock.patch.object(do, 'floor', side_effect=lambda task, root, row: ('高', basis) if row.get('candidate_id') else (None, None)):
            pa._auto_complete(dict(TASK, best_estimate_revision='best-estimate-risk-v2'), {}, decisions,
                              dict(zip(keys, (candidate, scope))), dict(zip(keys, (deepcopy(candidate), deepcopy(scope)))),
                              {'first': 'A', 'second': 'B'}, worksheet)
        rows = {row.get('candidate_id'): row for row in decisions}
        self.assertEqual(rows['CAND-1']['risk'], '高')
        self.assertEqual((rows[None]['risk'], rows[None]['assessment_status']), (None, 'pending'))
        self.assertEqual(rows[None]['pending_reasoning'], '该范围风险由候选USD1055634S1：Grilling basket决定。')
        self.assertTrue(rows[None]['adjudication_reasoning'])

    def test_decisive_exclusions_old_tasks_and_rows_at_the_floor_are_untouched(self):
        decisive = self.row('极低', decisive_exclusion={'reasoning': '届满', 'evidence_refs': ['EV-REC']})
        decisions, _ = self.settle(decisive, decisive)
        self.assertEqual(decisions, [])
        decisions, _ = self.settle(self.row('低'), self.row('低'), task={})
        self.assertEqual(decisions, [])
        decisions, _ = self.settle(self.row('中'), self.row('中'), level='中')
        self.assertEqual(decisions, [])


if __name__ == '__main__':
    unittest.main()
