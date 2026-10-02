"""Intent-group judgements, ledger rebind and advisory coverage (no network)."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from keyword_fixtures import keywords as k, make_run, write
from test_keyword_workflow import completed_run


WORDS = ['black cat door corner', 'topper corner door', 'microchip cat door', 'halloween black cat decor']


def fresh_run(root):
    profile = {'site': 'US', 'listing_mode': 'single',
               'product_identity': {'canonical_name': 'Black Cat Door Corner Decor', 'protected_terms': ['Black Cat Door Corner Decor']},
               'facts': [{'fact_id': 'shape', 'field': 'shape', 'value': 'black cat silhouette', 'status': 'confirmed', 'source_ref': 'drawing'},
                         {'fact_id': 'purpose', 'field': 'function', 'value': 'door frame ornament', 'status': 'confirmed', 'source_ref': 'spec'}]}
    write(root, k.PROFILE, profile)
    write(root, k.RAW, {'keywords': WORDS, 'raw': {'keyword_data': [{'keyword': w, 'searches': n} for w, n in zip(WORDS, (900, 40, 300, 700))]}})
    with contextlib.redirect_stdout(io.StringIO()):
        assert k.main(['prepare', '--run-dir', str(root)]) == 0
    return profile


GROUPS = {'reviewer': 'model-first-pass', 'groups': {
    'door-corner-decor': {'decision': 'eligible', 'reason_code': 'identity', 'role': 'identity', 'label': 'high',
                          'reason': '完整对象均为门角猫轮廓装饰，词序不同不改变意图。', 'query_intent': '寻找门框角落的猫造型装饰',
                          'evidence': 'product_identity 与 purpose 事实', 'fact_ids': ['purpose'], 'identity_basis': True,
                          'applies_to': ['all'], 'keywords': ['black cat door corner', 'topper corner door', 'Black Cat Door Corner Decor']},
    'pet-flap': {'decision': 'excluded', 'reason_code': 'product_mismatch', 'role': 'identity', 'label': 'relevant',
                 'reason': '芯片宠物门是宠物通道，本品是门框装饰。', 'query_intent': '寻找带芯片识别的宠物门',
                 'evidence': 'purpose 事实为门框装饰', 'fact_ids': ['purpose'], 'applies_to': ['all'], 'keywords': ['microchip cat door']},
    'halloween': {'decision': 'deferred', 'reason_code': 'seasonal_unconfirmed', 'role': 'intent', 'label': 'relevant',
                  'reason': '黑猫可联想万圣节，但节日定位未确认。', 'query_intent': '寻找万圣节黑猫装饰', 'evidence': '仅确认猫轮廓',
                  'fact_ids': ['shape'], 'applies_to': ['all'], 'promotion_condition': '确认本品可作万圣节装饰销售',
                  'keywords': ['halloween black cat decor']}}}


class IntentGroupTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup); self.run = Path(temp.name)
        self.profile = fresh_run(self.run)

    def apply(self, spec):
        write(self.run, 'groups.json', spec)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = k.main(['apply', '--run-dir', str(self.run), '--groups', str(self.run / 'groups.json')])
        return code, out.getvalue()

    def test_group_judgement_fills_per_keyword_ledger_that_passes_unchanged_checks(self):
        self.assertEqual(self.apply(GROUPS)[0], 0)
        ledger = k.read_json(self.run / k.DECISIONS)
        record = next(r for r in ledger['records'] if r['keyword'] == 'topper corner door')
        self.assertEqual((record['decision'], record['initial_decision'], record['intent_group'], record['reviewer']),
                         ('eligible', 'eligible', 'door-corner-decor', 'model-first-pass'))
        self.assertIn('door-corner-decor', ledger['intent_groups'])
        result = k.check_run(self.run, require_exports=False, downstream=False)
        self.assertEqual(result['status'], 'passed', result['issues'])
        view = (self.run / '03_keyword_view.tsv').read_text(encoding='utf-8').splitlines()
        self.assertTrue(view[1].startswith('black cat door corner\t900\t'))

    def test_partial_apply_leaves_rest_unreviewed_and_unknown_words_fail(self):
        spec = json.loads(json.dumps(GROUPS)); spec['groups'].pop('halloween')
        code, out = self.apply(spec)
        self.assertEqual(json.loads(out)['unreviewed'], 1)
        self.assertEqual(k.check_run(self.run, require_exports=False, downstream=False)['status'], 'incomplete')
        spec['groups']['door-corner-decor']['keywords'].append('not in raw list')
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.apply(spec)[0], 2)

    def test_override_changing_one_member_still_needs_group_difference(self):
        self.apply(GROUPS)
        spec = {'groups': {}, 'overrides': {'topper corner door': {'decision': 'deferred', 'reason_code': 'ambiguous_intent',
                'promotion_condition': '确认词序异常是否同一意图', 'resolution': '复查后暂缓'}}}
        self.apply(spec)
        codes = {i['code'] for i in k.check_run(self.run, require_exports=False, downstream=False)['issues']}
        self.assertIn('keyword_intent_conflict', codes)

    def test_rebind_names_only_keywords_using_changed_facts(self):
        self.apply(GROUPS)
        self.profile['facts'][0]['value'] = 'black cat silhouette with arched back'
        self.profile['facts'].append({'fact_id': 'colour', 'field': 'color', 'value': 'black', 'status': 'confirmed', 'source_ref': 'photo'})
        write(self.run, k.PROFILE, self.profile)
        self.assertIn('keyword_source_stale', {i['code'] for i in k.check_run(self.run, False, False)['issues']})
        result = k.rebind(self.run)
        self.assertEqual((result['rebound'], result['affected']), (False, ['halloween black cat decor']))
        self.assertTrue(k.rebind(self.run, reviewed=True)['rebound'])
        self.assertEqual(k.check_run(self.run, False, False)['status'], 'passed')


class CoverageTests(unittest.TestCase):
    def test_coverage_reports_uncovered_traffic_and_rewrites_placement_from_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            completed_run(run)
            raw = k.read_json(run / k.RAW)
            raw['raw']['keyword_data'] = [{'keyword': 'Pen Holder', 'searches': 500}, {'keyword': 'stationery organizer', 'searches': 80}]
            write(run, k.RAW, raw)
            profile = k.read_json(run / k.PROFILE)
            profile['intent_map'] = [{'relation': 'location', 'expression': 'desk', 'fact_ids': [], 'applies_to': ['all']},
                                     {'relation': 'audience', 'expression': 'students', 'fact_ids': [], 'applies_to': ['all']}]
            write(run, k.PROFILE, profile)
            report = k.coverage(run, write_placement=True)
            single = report['targets']['single']
            self.assertEqual(single['token_covered'], single['eligible'])
            self.assertEqual(single['searches_weighted_token_coverage'], 1.0)
            self.assertEqual([e['missing_for'] for e in report['intent_map']], [[], ['single']])
            self.assertEqual(report['fact_unlocks'][0]['keywords'], ['iron pen holder'])
            plan = k.read_json(run / '05_title_keywords.json')['placement_plan']
            self.assertIn({'keyword': 'Pen Holder', 'target_field': 'title', 'applies_to': ['all'],
                           'reason': 'coverage 工具按最终文案中的完整短语位置生成'}, plan)
            self.assertEqual(k.check_usage(profile, k.read_json(run / k.DECISIONS), k.read_json(run / '05_title_keywords.json')), [])
            from test_render_listing import renderer, ScriptCollector
            markdown, page, _ = renderer.build_report(run)
            self.assertIn('## 后台属性建议\n\n- material：304 Stainless Steel', markdown)
            headings = [line for line in markdown.splitlines() if line.startswith('## ')]
            self.assertEqual(headings.index('## 后台属性建议'), headings.index('## Search Terms') + 1)
            parsed = ScriptCollector(); parsed.feed(page)
            self.assertEqual(json.loads(parsed.values['data-coverage'])['targets']['single']['eligible'], single['eligible'])
            self.assertEqual(sum(tag == 'section' and attrs.get('class') == 'chapter' for tag, attrs in parsed.tags), 7)


if __name__ == '__main__':
    unittest.main()


class ClusterProposalTests(unittest.TestCase):
    WORDS = ['pen holder', 'metal pen holder', 'pen holder for desk', 'cute pen holder', 'desk organizer',
             'mesh desk organizer', 'desk organizer with drawer', 'wooden desk organizer', 'microchip cat door']

    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup); self.run = Path(temp.name)
        write(self.run, k.PROFILE, {'site': 'US', 'listing_mode': 'single',
                                    'product_identity': {'canonical_name': 'Pen Holder', 'protected_terms': ['Pen Holder']},
                                    'facts': [{'fact_id': 'use', 'field': 'function', 'value': 'holds pens on a desk', 'status': 'confirmed', 'source_ref': 'spec'}]})
        write(self.run, k.RAW, {'keywords': self.WORDS, 'raw': {'keyword_data': [
            {'keyword': w, 'monthly_searches': 1000 - i, 'source_file_count': 3 if 'pen' in w else 1} for i, w in enumerate(self.WORDS)]}})
        with contextlib.redirect_stdout(io.StringIO()):
            k.main(['prepare', '--run-dir', str(self.run)])

    def test_view_clusters_propose_head_groups_and_apply_accepts_cluster_with_exceptions(self):
        summary = k.write_view(self.run, clusters=True)
        proposal = k.read_json(self.run / k.CLUSTERS)['clusters']
        heads = {c['head']: c['cluster_id'] for c in proposal}
        self.assertEqual(set(heads), {'pen holder', 'desk organizer', '~door'})
        self.assertEqual(summary['clusters'], 3)
        header, first = (self.run / '03_keyword_view.tsv').read_text(encoding='utf-8').splitlines()[:2]
        self.assertIn('\tsources\t', header)
        self.assertTrue(first.startswith('pen holder\t1000\t'))
        spec = {'reviewer': 'cluster-test', 'groups': {
            'pen-holder': dict(GROUPS['groups']['door-corner-decor'], fact_ids=['use'], keywords=['@' + heads['pen holder'], 'Pen Holder'],
                               **{'except': ['cute pen holder']}),
            'desk-organizer': dict(GROUPS['groups']['door-corner-decor'], reason_code='synonym', role='synonym', fact_ids=['use'],
                                   keywords=['@' + heads['desk organizer']]),
            'other': dict(GROUPS['groups']['pet-flap'], keywords=['@' + heads['~door'], 'cute pen holder'])}}
        write(self.run, 'groups.json', spec)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(k.main(['apply', '--run-dir', str(self.run), '--groups', str(self.run / 'groups.json')]), 0)
        self.assertEqual(json.loads(out.getvalue())['unreviewed'], 0)
        ledger = k.read_json(self.run / k.DECISIONS)
        decision = {r['keyword']: r['decision'] for r in k.all_records(ledger)}
        self.assertEqual((decision['metal pen holder'], decision['cute pen holder'], decision['wooden desk organizer']),
                         ('eligible', 'excluded', 'eligible'))

    def test_cluster_reference_requires_current_proposal(self):
        write(self.run, 'groups.json', {'groups': {'g': dict(GROUPS['groups']['pet-flap'], keywords=['@c001'])}})
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(k.main(['apply', '--run-dir', str(self.run), '--groups', str(self.run / 'groups.json')]), 2)
