"""Offline behavioral regression: python3 -B -m unittest discover -s tests -v."""
import csv
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import csc
import csc_table as ct
import compliance_engine as ce


def category(form='other', evidence='实售商品是固体工具', families=None):
    return dict(families=families or [], children=False, battery='none', wireless=False, mains=False,
                primary_form=form, form_evidence=evidence)


class ScreeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = ce.RulePack.load(csc.PACK_PATH)
        cls.tables = csc._business_tables()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def write_json(self, name, data):
        path = self.root / name
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return str(path)

    def cli(self, *args):
        output = io.StringIO()
        with patch.object(sys, 'argv', ['csc.py', *map(str, args)]), redirect_stdout(output), patch.object(csc, 'require_auth'):
            try:
                csc.main()
            except SystemExit as exc:
                code = exc.code or 0
            else:
                code = 0
        return code, json.loads(output.getvalue())

    def table(self, header, rows, cats=None, pages=None, fetch='never'):
        source = self.root / 'source.csv'
        with source.open('w', encoding='utf-8', newline='') as f:
            csv.writer(f).writerows([header, *rows])
        args = ['table', '--input', source, '--out', self.root / 'result.csv', '--fetch', fetch]
        if cats is not None:
            args += ['--categories', self.write_json('categories.json', cats)]
        if pages is not None:
            args += ['--pages', self.write_json('pages.json', pages)]
        return self.cli(*args)

    def marked(self, title, cat, site='US'):
        screen = csc._screen(self.pack, {'title': title}, site, cat)[0]
        return csc._mark(screen, self.pack, self.tables)

    def test_header_aliases_and_seller_country(self):
        header = ['卖家所处国家', '产品卖点', '商品标题', '亮点', '产品描述', '来源店铺URL', '商品URL']
        cols = ct.detect_columns(header)
        self.assertEqual(cols['bullets'], [1, 3])
        self.assertEqual(cols['title'], [2])
        self.assertEqual(cols['url'], [6])
        self.assertNotIn('site', cols)
        self.assertEqual(ct.detect_columns(['标题', '五点1', '五点2', '站点'])['bullets'], [1, 2])

    def test_full_evidence_in_pending_data(self):
        bullets = '\n'.join(['ordinary'] * 10 + ['liquid hair oil'])
        code, result = self.table(['标题', '亮点', '产品卖点', '描述', '商品URL'],
                                 [['Repair kit', '膏状护理品', bullets, '最后一段：cream', 'https://amazon.com/dp/X']])
        self.assertEqual(code, 0)
        self.assertFalse(result['classification_complete'])
        pending = json.loads(Path(result['categories_todo']).read_text(encoding="utf-8"))[0]
        self.assertEqual(len(pending['bullets']), 12)
        self.assertIn('liquid hair oil', pending['bullets'])
        self.assertEqual(pending['description'], '最后一段：cream')

    def test_old_classification_is_not_silently_complete(self):
        cat = category()
        del cat['primary_form']
        code, result = self.table(['标题', '商品URL'], [['面霜', 'https://amazon.com/dp/X']], {'2': cat})
        self.assertEqual(code, 0)
        self.assertEqual(result['uncategorized'], 1)
        self.assertEqual(result['marks'], {'无法判断': 1})

    def test_unknown_is_processed_but_not_cleared(self):
        result = self.marked('XQ-900', category('unknown', ''))
        self.assertTrue(result['classification_complete'])
        self.assertEqual(result['mark'], '无法判断')
        self.assertFalse(result['logistics_restricted'])

    def test_invalid_form_and_missing_evidence_rejected(self):
        for cat in (category('water'), category('liquid', '')):
            code, result = self.cli('quick', '--title', 'Oil', '--category', json.dumps(cat), '--fetch', 'never')
            self.assertEqual(code, 2)
            self.assertFalse(result['ok'])

    def test_semantic_decision_controls_policy_not_keywords(self):
        cases = [('Hair Styling Clay', 'paste_gel', True), ('Travel Cream Jars Empty', 'other', False),
                 ('Repair Set', 'liquid', True), ('Oil Diffuser with free 5ml oil', 'other', False),
                 ('Solid Shampoo Bar not liquid', 'other', False), ('Ice Cream Resin Figurine', 'other', False),
                 ('Silicone Makeup Brush for Cream', 'other', False), ('Toothpaste', 'paste_gel', True),
                 ('Soft Hair Wax', 'paste_gel', True), ('Glass bottle sold with 500ml olive oil', 'liquid', True),
                 ('Garden Fountain water not included', 'other', False), ('液体肥料', 'liquid', True),
                 ('密封重复使用凝胶冰袋', 'other', False)]
        for title, form, expected in cases:
            with self.subTest(title=title):
                result = self.marked(title, category(form, title))
                self.assertEqual(result['logistics_restricted'], expected)

    def test_logistics_applies_to_all_ten_sites(self):
        for site in ce.SITES:
            with self.subTest(site=site):
                result = self.marked('Hair Styling Clay', category('paste_gel', 'Hair Styling Clay', ['cosmetics']), site)
                self.assertTrue(result['logistics_restricted'])
                self.assertIn(result['mark'], ('禁售', '需平台审核', '物流运输强限制'))

    def test_priority_costs_and_summary_survive_overlay(self):
        for mark in ct.MARKS:
            with self.subTest(mark=mark):
                base = dict(mark=mark, detail='原始合规事项', paid_items=['CPC'], factory_items=['UN38.3'])
                result = ct.finalize_mark(base, category('liquid', '液体'))
                self.assertEqual(result['mark'], mark if mark in ('禁售', '需平台审核') else '物流运输强限制')
                self.assertIn('原始合规事项', result['detail'])
                self.assertIn('CPC', result['detail'])
                summary = csc._summary([result])
                self.assertEqual(summary['requirement_counts']['paid_items']['CPC'], 1)
                self.assertEqual(len(summary['logistics_products']), 1)
                self.assertEqual(summary['logistics_count'], 1)

    def test_only_title_and_empty_optional_columns(self):
        code, result = self.table(['标题', '亮点', '产品卖点', '商品URL'],
                                 [['Hair clay', '', '', 'https://amazon.com/dp/X']],
                                 {'2': category('paste_gel', 'Hair clay', ['cosmetics'])})
        self.assertEqual(code, 0)
        self.assertTrue(result['classification_complete'])
        self.assertEqual(result['marks'], {'物流运输强限制': 1})

    def test_short_link_page_before_site_and_classification(self):
        page = dict(title='Hair clay', bullets=['膏状'], description='完整内容', final_url='https://amazon.de/dp/X')
        with patch.object(ct, 'fetch_page', return_value=(page, None)):
            code, result = self.table(['商品URL'], [['https://amzn.to/x']], fetch='auto')
        self.assertEqual(code, 0)
        self.assertEqual(result['uncategorized'], 1)
        self.assertIn('pages_read', result)
        pending = json.loads(Path(result['categories_todo']).read_text(encoding="utf-8"))[0]
        self.assertEqual(pending['url'], page['final_url'])
        self.assertEqual(pending['title'], 'Hair clay')

    def test_provided_pages_do_not_fetch_and_use_landing_site(self):
        page = dict(title='Hair clay', bullets=['膏状'], final_url='https://amazon.co.jp/dp/X')
        with patch.object(ct, 'fetch_page', side_effect=AssertionError('unexpected fetch')):
            code, result = self.cli('quick', '--url', 'https://amzn.to/x', '--page', self.write_json('page.json', page),
                                    '--category', json.dumps(category('paste_gel', '膏状', ['cosmetics'])))
        self.assertEqual(code, 0)
        self.assertEqual([r['site'] for r in result['sites']], ['JP'])
        self.assertTrue(result['classification_complete'])

    def test_fresh_page_requires_semantic_pass(self):
        page = dict(title='Oil', bullets=['Liquid'], final_url='https://amazon.com/dp/X')
        with patch.object(ct, 'fetch_page', return_value=(page, None)):
            code, result = self.cli('quick', '--url', 'https://amazon.com/dp/X',
                                    '--category', json.dumps(category('other')))
        self.assertEqual(code, 0)
        self.assertFalse(result['classification_complete'])
        self.assertEqual(result['product_for_classification']['bullets'], ['Liquid'])

    def test_link_failure_is_not_cleared(self):
        with patch.object(ct, 'fetch_page', return_value=(None, '验证码')):
            code, result = self.cli('quick', '--url', 'https://amazon.com/dp/X')
            self.assertEqual(code, 2)
            code, result = self.table(['商品URL'], [['https://amazon.com/dp/X']], fetch='auto')
        self.assertEqual(result['marks'], {'无法判断': 1})
        self.assertFalse(result['classification_complete'])

    def test_unresolved_site_does_not_default(self):
        code, result = self.cli('quick', '--title', 'Oil', '--url', 'https://amzn.to/x', '--fetch', 'never')
        self.assertEqual(code, 2)
        code, result = self.table(['标题', '卖家所处国家'], [['Oil', '中国']])
        self.assertEqual(result['marks'], {'无法判断': 1})

    def test_page_reader_preserves_all_bullets_and_redirect(self):
        body = '<span id="productTitle">Oil</span><div id="feature-bullets"><ul>'
        body += ''.join(f'<li>bullet {i}</li>' for i in range(12)) + '</ul></div>'
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, size): return body.encode()
            def geturl(self): return 'https://amazon.fr/dp/X'
        with patch.object(ct.urllib.request, 'urlopen', return_value=Response()):
            page, error = ct.fetch_page('https://amzn.to/x')
        self.assertIsNone(error)
        self.assertEqual(len(page['bullets']), 12)
        self.assertEqual(page['final_url'], 'https://amazon.fr/dp/X')

    def test_quick_table_and_saved_reports_agree(self):
        cat = category('paste_gel', '造型发泥', ['cosmetics'])
        code, quick = self.cli('quick', '--title', '造型发泥', '--sites', 'US', '--category', json.dumps(cat),
                               '--out', self.root / 'report', '--fetch', 'never')
        self.assertEqual(code, 0)
        saved = json.loads((self.root / 'report/quick_result.json').read_text(encoding="utf-8"))
        row = quick['sites'][0]
        self.assertEqual((saved['sites'][0]['mark'], saved['sites'][0]['detail']), (row['mark'], row['detail']))
        for name in ('report.html', 'report.md', 'findings.csv'):
            self.assertIn(row['mark'], (self.root / 'report' / name).read_text(encoding="utf-8"))
        code, table = self.table(['标题', '站点'], [['造型发泥', 'US']], {'2': cat})
        with Path(table['table']).open(encoding='utf-8-sig') as f:
            result_row = list(csv.reader(f))[1]
        self.assertEqual(result_row[-2:], [row['mark'], row['detail']])
        self.assertTrue(any('MoCRA' in k for k in table['requirement_counts']['paid_items']))

    def test_formal_profile_and_view_preserve_legal_result(self):
        facts = ce.make_facts({'title': 'Hair Clay'}, [], ['US'])
        profile = ce.profile_template(self.pack, facts)
        profile['families'] = [{'id': 'cosmetics', 'evidence': ['title']}]
        profile['attributes']['substance.primary_form'] = {
            'value': 'paste_gel', 'status': 'inferred', 'evidence': ['title'], 'note': '发泥常见膏状'}
        profile, errors = ce.validate_profile(self.pack, facts, profile)
        self.assertEqual(errors, [])
        self.assertEqual(profile['attributes']['substance.primary_form']['note'], '发泥常见膏状')
        result = dict(site='US', verdict='needs_info', fba='unknown', confidence='low', applied=[], requirements=[])
        business = csc._formal_mark(self.pack, profile, facts, result)
        view = ce.build_view(self.pack, facts, {'sites': [result]}, 'draft', profile,
                             {'business_results': {'US': business}})
        self.assertEqual(view['sites'][0]['mark'], '物流运输强限制')
        self.assertEqual(view['sites'][0]['verdict'], 'needs_info')
        self.assertEqual(view['sites'][0]['fba'], 'unknown')
        self.assertIn('物流运输强限制', ce.render_html(view))
        self.assertIn('物流运输强限制', ce.render_markdown(view))
        profile['attributes']['substance.primary_form'] = {'value': None, 'status': 'unknown', 'evidence': []}
        unknown = csc._formal_mark(self.pack, profile, facts, result)
        self.assertEqual(unknown['mark'], '无法判断')

    def test_formal_render_persistence(self):
        task = self.root / 'task'
        source = self.write_json('product.json', {'title': 'Hair Clay', 'bullets': ['detail'] * 11})
        code, result = self.cli('init', '--input', source, '--sites', 'US', '--task', task)
        self.assertEqual(code, 0)
        facts = json.loads((task / 'facts.json').read_text(encoding="utf-8"))
        self.assertEqual(len(facts['product']['bullets']), 11)
        profile = json.loads((task / 'profile.template.json').read_text(encoding="utf-8"))
        profile['families'] = [{'id': 'cosmetics', 'evidence': ['title']}]
        profile['attributes']['substance.primary_form'] = {
            'value': 'paste_gel', 'status': 'inferred', 'evidence': ['title'], 'note': '发泥常见膏状'}
        code, matched = self.cli('match', '--task', task, '--profile', self.write_json('formal-profile.json', profile))
        self.assertEqual(code, 0)
        # Reviewed legal assessment fixture: render must not alter this dimension.
        assessment = dict(report_mode='draft', sites=[dict(site='US', verdict='needs_info', fba='unknown',
                                                           confidence='low', applied=[], requirements=[])])
        (task / 'assessment.json').write_text(json.dumps(assessment), encoding="utf-8")
        state = json.loads((task / 'task.json').read_text(encoding="utf-8"))
        state['step'] = 'reviewed'
        (task / 'task.json').write_text(json.dumps(state), encoding="utf-8")
        code, rendered = self.cli('render', '--task', task)
        self.assertEqual(code, 0)
        saved = json.loads((task / 'report_data.json').read_text(encoding="utf-8"))
        self.assertEqual(rendered['sites'][0]['mark'], '物流运输强限制')
        self.assertEqual(saved['sites'][0]['detail'], rendered['sites'][0]['detail'])
        self.assertEqual(json.loads((task / 'assessment.json').read_text(encoding="utf-8")), assessment)

    def test_long_description_survives_page_merge(self):
        description = 'x' * 6000 + '此处为液体护发油'
        code, result = self.cli('quick', '--url', 'https://amazon.com/dp/X', '--page',
                                self.write_json('long-page.json', dict(title='Care kit', description=description,
                                                                       bullets=['point'] * 11)))
        self.assertEqual(code, 0)
        self.assertEqual(result['product_for_classification']['description'], description)
        self.assertEqual(len(result['product_for_classification']['bullets']), 11)


if __name__ == '__main__':
    unittest.main()
