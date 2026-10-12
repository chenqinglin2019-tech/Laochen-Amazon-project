from __future__ import annotations

import contextlib
import io
import itertools
import json
import random
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

import test_niche_recommendation as fixture
from test_refine_inputs import write_workbook
niche = fixture.niche


class PipelineTests(unittest.TestCase):
    def setup_fixture(self, directory):
        project, poe, definitions = fixture.NicheRecommendationIntegrationTests()._build_project(Path(directory))
        # Fully valid product sample; the arithmetic mean is deliberately constant.
        source = project / 'market_research/cleaned_30d_listings.json'
        data = json.loads(source.read_text())
        for row in data['rows']:
            row['price'] = 20
        source.write_text(json.dumps(data))
        fixture._xlsx(project / 'keywords.xlsx', '关键词', [
            ['关键词', '月搜索量', '月购买量', 'PPC竞价'],
            ['truck phone mount', 500, 50, 1], ['phone mount for truck', 100, 10, 3]])
        data = json.loads(definitions.read_text())
        data['candidates'][0]['keyword_assignments'].append({'keyword': 'phone mount for truck', 'type': 'direct', 'reason': '明确卡车手机固定需求'})
        definitions.write_text(json.dumps(data))
        conversion = project / 'new_keyword_conversions.xlsx'
        # Bid-like columns in the conversion workbook must be ignored: bids come only from SellerSprite.
        fixture._xlsx(conversion, '关键词转化', [['关键词', '近90天点击量', '近90天购买量', '统计周期', '站点', 'PPC竞价', '建议出价 ($)', '最高出价 ($)'],
                  ['truck phone mount', 800, 80, '2026-06-01/2026-08-29', 'US', 999, 999, 999],
                  ['phone mount for truck', 400, 20, '2026-06-01/2026-08-29', 'US', .001, .001, .001]])
        seller = project / 'sellersprite_truck.xlsx'
        write_workbook(seller, {'US-B0TEST0009(10)': [['关键词', 'PPC竞价', '流量占比'], ['truck phone mount', '$1.00', '60%'], ['phone mount for truck', '$3.00', '40%']],
                                'Asin': [['ASIN']] + [[f'B0TEST{i:04d}'] for i in range(10)]})
        first = ['shortlist', '--project-root', str(project), '--poe-xlsx', str(poe), '--definitions', str(definitions)]
        second = ['refine', '--project-root', str(project), '--shortlist-result', str(project / 'market_opportunity/niche_shortlist.json'),
                  '--keyword-input-xlsx', str(conversion), str(seller)]
        return project, poe, definitions, conversion, first, second

    def run_cli(self, command):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return niche.main(command)

    def test_full_pipeline_uses_full_conversion_and_click_weighted_cpc(self):
        with tempfile.TemporaryDirectory() as directory:
            project, _, _, _, first, second = self.setup_fixture(directory)
            folder = project / 'market_opportunity'
            original = (folder / '市场机会深挖看板.html').read_bytes()
            self.assertEqual(0, self.run_cli(first))
            self.assertFalse((folder / '08_niche_recommendations.json').exists())
            shortlist_bytes = (folder / 'niche_shortlist.json').read_bytes()
            shortlist = json.loads(shortlist_bytes)
            self.assertEqual(0, self.run_cli(second))
            result = json.loads((folder / '08_niche_recommendations.json').read_text())
            self.assertEqual('refine', result['stage'])
            candidate = result['candidates'][0]
            self.assertEqual(['truck_cabin_phone_hold'], result['selected_candidate_ids'])
            ad = candidate['ad_cost_evidence']
            self.assertAlmostEqual(5 / 3, ad['representative_bid'])
            self.assertAlmostEqual(100 / 1200, ad['click_conversion_rate'])
            self.assertAlmostEqual(100, ad['pressure_estimate'])
            self.assertAlmostEqual(20, ad['mean_price'])
            self.assertEqual(shortlist['candidates'][0]['supply_demand_evidence'], candidate['supply_demand_evidence'])
            self.assertNotIn('return_risk', candidate['scoring']['components'])
            rules = candidate['rule_conclusions']['rules']
            self.assertEqual(8, len(rules))
            self.assertAlmostEqual(ad['pressure_estimate'], rules['ad_pressure']['value'])
            self.assertAlmostEqual(candidate['refined_product_evidence']['product_head_share_pct'], rules['product_monopoly']['value'])
            self.assertAlmostEqual(candidate['refined_product_evidence']['brand_head_share_pct'], rules['brand_monopoly']['value'])
            self.assertEqual(shortlist['selected_candidate_ids'], result['selected_candidate_ids'])
            self.assertEqual(shortlist['candidates'][0]['scoring'], candidate['scoring'])
            self.assertEqual('partial', result['deep_analysis_status'])
            self.assertEqual('partial', candidate['deep_analysis_status'])
            self.assertEqual(10, len(candidate['top20']))
            self.assertEqual('B0TEST0009', candidate['top20'][0]['asin'])
            self.assertEqual(shortlist_bytes, (folder / 'niche_shortlist.json').read_bytes())
            self.assertEqual(original, (folder / '市场机会深挖看板.html').read_bytes())
            report = (folder / '市场机会深挖看板-两轮复评.html').read_text()
            self.assertIn('id="niche-final-top3"', report)
            self.assertIn('100.00%', report)
            receipt = json.loads((folder / 'niche_recommendation_run.json').read_text())
            self.assertGreaterEqual(receipt['elapsed_since_shortlist_seconds'], 0)
            for filename, digest in receipt['output_hashes'].items():
                self.assertEqual(digest, niche.sha256_file(folder / filename))
            first_id = result['run_id']
            self.assertEqual(0, self.run_cli(second))
            self.assertEqual(first_id, json.loads((folder / '08_niche_recommendations.json').read_text())['run_id'])

    def test_shortlist_failure_invalidates_final_handoff_state(self):
        with tempfile.TemporaryDirectory() as directory:
            project, _, definitions, _, first, second = self.setup_fixture(directory)
            self.assertEqual(0, self.run_cli(first)); self.assertEqual(0, self.run_cli(second))
            definitions.write_text('{}')
            self.assertEqual(2, self.run_cli(first))
            manifest = json.loads((project / 'project_manifest.json').read_text())
            self.assertEqual('shortlist_failed', manifest['status']['niche_recommendation'])
            self.assertEqual(2, self.run_cli(second))

    def test_refine_rejects_shortlist_from_previous_supply_demand_rule(self):
        with tempfile.TemporaryDirectory() as directory:
            project, _, _, _, first, second = self.setup_fixture(directory)
            self.assertEqual(0, self.run_cli(first))
            shortlist_path = project / 'market_opportunity/niche_shortlist.json'
            shortlist = json.loads(shortlist_path.read_text())
            shortlist['rule_version'] = 'niche_recommendation_v6_supply_demand_dominant'
            shortlist_path.write_text(json.dumps(shortlist))
            self.assertEqual(2, self.run_cli(second))

    def test_inconsistent_purchase_click_counts_cannot_get_cheap_ad_score(self):
        engine = niche.helper_module('niche_refinement_metrics')
        ad = engine.advertising_evidence([{'keyword': 'truck phone mount', 'clicks': 10, 'purchases': 100, 'ppc_bid': 2, 'conversion_available': True}], 20)
        self.assertNotEqual('ready', ad['status'])
        self.assertIsNone(ad['pressure_estimate'])

    def test_three_markets_one_missing_sellersprite_bids_is_partial_not_dropped(self):
        with tempfile.TemporaryDirectory() as directory:
            project, poe, definitions, conversion, first, second = self.setup_fixture(directory)
            folder = project / 'market_opportunity'
            proto = json.loads(definitions.read_text())['candidates'][0]
            poe_rows = [['细分市场名称', '细分市场分类1']]
            candidates, dispositions, products, tags = [], [], [], []
            kw_rows = [['关键词', '月搜索量']]
            for index in range(12):
                key = f'segment{index:02}'
                keyword = f'phone mount for {key}'
                candidate = json.loads(json.dumps(proto))
                candidate.update(id=key, name=key, dedupe_group=key, primary_poe_row_number=index + 2,
                                 tag_expression={'any_of': [{'all_of': [{'dimension': '车型适配', 'values': [key]}]}]},
                                 poe_matches=[{'row_number': index + 2, 'relationship': 'exact', 'reason': '准确需求'}],
                                 keyword_assignments=[{'keyword': keyword, 'type': 'direct', 'reason': '完整核心需求'}])
                candidates.append(candidate)
                dispositions.append({'row_number': index + 2, 'disposition': 'direct_need', 'reason': '准确需求', 'candidate_ids': [key]})
                poe_rows.append([key, 'Vehicle fit'])
                kw_rows.append([keyword, 500 + index])
                for j in range(10):
                    asin = f'B0S{index:03}{j:04}'
                    products.append({'asin': asin, 'price': 20, 'monthly_sales': 10 + index * 3 + j, 'brand': f'brand{j % 3}', 'launch_days': 100 + j * 40, 'review_count': 10, 'rating': 4.5})
                    tags.append({'asin': asin, 'normalized_values': {'车型适配': [key]}, 'display_values': {'车型适配': [key]}})
            fixture._xlsx(poe, '细分市场列表', poe_rows)
            fixture._xlsx(project / 'keywords.xlsx', '关键词', kw_rows)
            definitions.write_text(json.dumps({'project_id': 'market_project_fixture', 'candidates': candidates, 'poe_row_dispositions': dispositions}))
            (project / 'market_research/cleaned_30d_listings.json').write_text(json.dumps({'rows': products}))
            (folder / 'agent_listing_tags.json').write_text(json.dumps({'tags': tags}))
            self.assertEqual(0, self.run_cli(first))
            shortlist = json.loads((folder / 'niche_shortlist.json').read_text())
            selected = shortlist['selected_candidate_ids']
            self.assertEqual(3, len(selected))
            files = []
            for position, key in enumerate(selected):
                market = next(c for c in shortlist['candidates'] if c['id'] == key)
                words = [f'{key} word {n}' for n in range(5)]
                conv = project / f'conv_{key}.xlsx'
                fixture._xlsx(conv, '关键词转化', [['关键词', '近90天点击量', '近90天购买量']] + [[w, 1000, 100] for w in words])
                bids = [None] * 5 if position == 0 else [1.0] * 5  # first market: SellerSprite gives no bids
                seller = project / f'seller_{key}.xlsx'
                write_workbook(seller, {'关键词': [['关键词', 'PPC竞价', '流量占比']] + [[w, b if b is not None else '', '20%'] for w, b in zip(words, bids)],
                                        'Asin': [['ASIN']] + [[m['asin']] for m in market['top20']]})
                files += [conv, seller]
            command = ['refine', '--project-root', str(project), '--shortlist-result', str(folder / 'niche_shortlist.json'), '--keyword-input-xlsx', *map(str, files)]
            self.assertEqual(0, self.run_cli(command))
            result = json.loads((folder / '08_niche_recommendations.json').read_text())
            self.assertEqual(selected, result['selected_candidate_ids'])
            by_id = {c['id']: c for c in result['candidates']}
            self.assertEqual('pending_validation', by_id[selected[0]]['ad_cost_evidence']['status'])
            self.assertIn('no_keywords_with_both_conversion_and_bid', by_id[selected[0]]['ad_cost_evidence']['reasons'])
            for key in selected[1:]:
                self.assertEqual('ready', by_id[key]['ad_cost_evidence']['status'])
                self.assertEqual(8, len(by_id[key]['rule_conclusions']['rules']))
            receipt = json.loads((folder / 'niche_recommendation_run.json').read_text())
            self.assertTrue({'data_import', 'matching', 'scoring', 'selection', 'rendering'} <= set(receipt['timings_seconds']))
            manifest = json.loads((project / 'project_manifest.json').read_text())
            self.assertEqual('refinement_pending', manifest['status']['niche_recommendation'])

    def test_frozen_input_change_rejected_and_previous_final_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            project, _, _, _, first, second = self.setup_fixture(directory)
            self.assertEqual(0, self.run_cli(first)); self.assertEqual(0, self.run_cli(second))
            folder = project / 'market_opportunity'
            old = (folder / '08_niche_recommendations.json').read_bytes()
            tags = folder / 'agent_listing_tags.json'
            tags.write_text(tags.read_text() + '\n')
            self.assertEqual(2, self.run_cli(second))
            self.assertEqual(old, (folder / '08_niche_recommendations.json').read_bytes())
            self.assertEqual('failed', json.loads((folder / 'niche_recommendation_run.json').read_text())['status'])

    def test_partial_poe_row_never_scores_but_keyword_evidence_counts(self):
        # v10: POE rows are demand evidence and reference only; all four components come from the product sample.
        with tempfile.TemporaryDirectory() as directory:
            project, _, definitions, _, first, _ = self.setup_fixture(directory)
            data = json.loads(definitions.read_text())
            data['candidates'][0]['poe_matches'][0]['relationship'] = 'partial'
            definitions.write_text(json.dumps(data))
            self.assertEqual(0, self.run_cli(first))
            result = json.loads((project / 'market_opportunity/niche_shortlist.json').read_text())
            candidate = result['candidates'][0]
            self.assertEqual('not_applicable', candidate['primary_poe']['status'])
            self.assertEqual('product_sample', candidate['competition_openness_evidence']['source'])
            self.assertEqual('product_sample', candidate['new_product_evidence']['source'])
            self.assertEqual(['truck_cabin_phone_hold'], result['selected_candidate_ids'])

    def test_no_keyword_search_and_no_exact_poe_row_is_not_formal(self):
        with tempfile.TemporaryDirectory() as directory:
            project, _, definitions, _, first, _ = self.setup_fixture(directory)
            fixture._xlsx(project / 'keywords.xlsx', '关键词', [['关键词', '月搜索量'], ['truck phone mount', 0], ['phone mount for truck', 0]])
            data = json.loads(definitions.read_text())
            data['candidates'][0]['poe_matches'][0]['relationship'] = 'partial'
            definitions.write_text(json.dumps(data))
            self.assertEqual(0, self.run_cli(first))
            result = json.loads((project / 'market_opportunity/niche_shortlist.json').read_text())
            self.assertEqual([], result['selected_candidate_ids'])
            self.assertIn('需求证据不足', result['candidates'][0]['formal_ineligible_reason'])

    def test_conversion_window_is_required_and_not_mixed(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'conversion.xlsx'
            fixture._xlsx(file, '数据', [['关键词', '点击量', '购买量'], ['truck phone mount', 100, 10]])
            with self.assertRaises(niche.RecommendationError):
                niche.load_refinement_conversion_file(file, 'US', None)
            loaded = niche.load_refinement_conversion_file(file, 'US', '2026-06/08')
            self.assertEqual('2026-06/08', loaded['period'])
            fixture._xlsx(file, '数据', [['关键词', '点击量', '购买量', '周期'], ['truck phone mount', 100, 10, 'A'], ['phone mount for truck', 20, 2, 'B']])
            with self.assertRaises(niche.RecommendationError):
                niche.load_refinement_conversion_file(file, 'US', None)

    def test_bids_only_come_from_sellersprite_and_single_file_entry_is_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            project, _, _, conversion, first, second = self.setup_fixture(directory)
            self.assertEqual(0, self.run_cli(first))
            self.assertEqual(0, self.run_cli(second))
            ad = json.loads((project / 'market_opportunity/08_niche_recommendations.json').read_text())['candidates'][0]['ad_cost_evidence']
            self.assertEqual({1.0, 3.0}, {row['ppc_bid'] for row in ad['keyword_details']})
            legacy = ['refine', '--project-root', str(project), '--shortlist-result', str(project / 'market_opportunity/niche_shortlist.json'),
                      '--keyword-conversion-xlsx', str(conversion)]
            err = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                self.assertEqual(2, niche.main(legacy))
            self.assertIn('已停用', err.getvalue())

    def test_return_context_does_not_become_a_scoring_component(self):
        pool = niche.helper_module('niche_candidate_pool')
        members = [{'asin': f'B{i:09d}', 'monthly_sales': 100 - i, 'brand': f'b{i % 3}', 'launch_days': 100 + i * 40} for i in range(12)]
        competition, evidence = pool.product_competition(members, niche.valid_sales, niche.brand_identity)
        self.assertIsNotNone(competition)
        self.assertEqual('product_sample', evidence['source'])
        newcomer, new_evidence = pool.product_new_entry(members, niche.valid_sales)
        self.assertIsNotNone(newcomer)
        self.assertEqual(7, new_evidence['new_product_count'])
        self.assertEqual('unavailable', niche.return_risk_context({'status': 'available', 'metrics': {'return_rate_360d': None}})['status'])
        evaluations = [{'candidate': {'id': 'a'}, 'base_eligible': True, 'metrics': {'monthly_sales_known_sum': 10},
                        'keyword_metrics': {'direct_monthly_search': {'known_sum': 5}}}]
        niche.set_product_demand_scale_scores(evaluations)
        self.assertEqual(50, evaluations[0]['demand_scale_score'])

    def test_robust_supply_demand_uses_fixed_universe_head_removal_and_shrinkage(self):
        pool = niche.helper_module('niche_candidate_pool')
        members = [{'asin': f'B{i:09d}', 'monthly_sales': 200} for i in range(100)]
        evidence = pool.robust_supply_demand(members, 1000, 100000, niche.valid_sales)
        self.assertAlmostEqual(2.0, evidence['raw_index'])
        without_head = (19400 / 99400) / (97 / 997)
        self.assertAlmostEqual(without_head, evidence['index_without_head'])
        self.assertAlmostEqual((97 * without_head + 20) / 117, evidence['robust_index'])
        for index, expected in ((0.0, 0.0), (0.8, 30.0), (1.0, 50.0), (1.2, 70.0),
                                (1.4, 80.0), (1.6, 90.0), (1.8, 100.0), (9.0, 100.0),
                                (0.4, 15.0), (0.9, 40.0), (1.1, 60.0), (1.3, 75.0),
                                (1.5, 85.0), (1.7, 95.0)):
            self.assertAlmostEqual(expected, niche.linear_score(index, niche.SUPPLY_DEMAND_ANCHORS))
        same = pool.robust_supply_demand(list(reversed(members)), 1000, 100000, niche.valid_sales)
        self.assertEqual(evidence['robust_index'], same['robust_index'])
        # one blockbuster cannot carry a small market: raw index is high, robust index falls back toward 1.0
        spiky = [{'asin': 'B000000000', 'monthly_sales': 5000}] + [{'asin': f'B1{i:08d}', 'monthly_sales': 10} for i in range(11)]
        spiky_evidence = pool.robust_supply_demand(spiky, 1000, 100000, niche.valid_sales)
        self.assertGreater(spiky_evidence['raw_index'], 4)
        self.assertLess(spiky_evidence['robust_index'], 1.0)

    def test_percentage_points_and_excel_percent_styles(self):
        self.assertEqual(.87, niche.percentage_points(.87))
        self.assertEqual(-.5, niche.percentage_points(-.5))
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'units.xlsx'
            fixture._xlsx(file, '数据', [['rate'], [.0087]])
            with zipfile.ZipFile(file) as archive:
                contents = {name: archive.read(name) for name in archive.namelist()}
            contents['xl/styles.xml'] = b'<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><cellXfs count="1"><xf numFmtId="10"/></cellXfs></styleSheet>'
            with zipfile.ZipFile(file, 'w') as archive:
                for name, data in contents.items(): archive.writestr(name, data)
            rows = niche.read_xlsx_sheet(file, '数据')
            self.assertAlmostEqual(.87, niche.percentage_points(rows[1][1][0]))

    def test_false_and_unknown_is_excluded_and_non_candidate_condition_rejected(self):
        expression = {'any_of': [{'all_of': [{'dimension': '安装位', 'values': ['cup']}, {'dimension': '充电', 'values': ['wireless']}]}]}
        self.assertEqual(('excluded', []), niche.match_expression({'安装位': ['非候选安装位'], '充电': ['unrecognized']}, expression))
        self.assertEqual(('unresolved', ['充电']), niche.match_expression({'安装位': ['cup'], '充电': ['unrecognized']}, expression))
        with self.assertRaises(niche.RecommendationError):
            niche.validate_expression({'any_of': [{'all_of': [{'dimension': '位置', 'values': ['非候选安装位']}]}]}, {'available_values': {'位置': {'非候选安装位': '非候选安装位'}}}, 'a')


class SelectionTests(unittest.TestCase):
    def make(self, count, rng, conflict_rate):
        records = [{'candidate': {'id': f'n{i:03}'}, 'formal_eligible': True,
                    'scoring': {'score': rng.choice([20., 40., 60.]), 'lower_bound': 0},
                    'ad_cost_evidence': {'pressure_estimate': rng.choice([20., 30., 40.])},
                    'competition_openness_score': rng.choice([50., 60.]), 'dedupe_conflict_ids': set()} for i in range(count)]
        for a, b in itertools.combinations(records, 2):
            if rng.random() < conflict_rate:
                a['dedupe_conflict_ids'].add(b['candidate']['id']); b['dedupe_conflict_ids'].add(a['candidate']['id'])
        return records

    def key(self, group):
        return (-len(group), -sum(x['scoring']['score'] for x in group), -sum(x['competition_openness_score'] for x in group), tuple(sorted(x['candidate']['id'] for x in group)))

    def test_exact_matches_exhaustive_including_ties(self):
        rng = random.Random(42)
        for _ in range(80):
            records = self.make(9, rng, .25)
            k = rng.choice([3, 5, 10])
            legal = [group for n in range(1, min(k, len(records)) + 1) for group in itertools.combinations(records, n) if all(b['candidate']['id'] not in a['dedupe_conflict_ids'] for a, b in itertools.combinations(group, 2))]
            expected = min(legal, key=self.key)
            selected = niche.candidate_selection(records, k)['selected']
            self.assertEqual(self.key(expected), self.key(selected))

    def test_114_no_conflict_candidates_do_not_enumerate_combinations(self):
        records = self.make(114, random.Random(1), 0)
        started = time.perf_counter()
        selected = niche.candidate_selection(records, 3)['selected']
        self.assertEqual(3, len(selected))
        self.assertEqual(niche.rank_key(sorted(records, key=niche.rank_key)[0]), niche.rank_key(selected[0]))
        self.assertLess(time.perf_counter() - started, 1)


if __name__ == '__main__':
    unittest.main()
