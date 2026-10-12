"""Behavioral checks for additive report rendering and safe evidence display."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "niche_two_round_report.py"
SPEC = importlib.util.spec_from_file_location("niche_two_round_report", MODULE_PATH)
report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(report)

BASE = '''<!doctype html>
<html><head><meta name="viewport" content="width=device-width, initial-scale=1">
<style>.original { color: blue; }</style></head><body>
<main><nav class="sidebar"><a href="#formal">正式组合</a> <a href="#small">小样本</a></nav>
<div class="content"><h2 id="formal">正式机会组合明细</h2>
<details><summary>原有组合</summary><svg viewBox="0 0 1 1"><path d="M0 0"/></svg></details>
 <h2 id="small">小样本观察</h2><p>原有正文 &amp; 引用。</p></div></main></body></html>'''


def candidate(identifier: str = "cup") -> dict:
    return {
        "id": identifier, "name": "杯架位固定手机", "definition": "在杯架位固定手机，保持可视。",
        "task": "车内固定手机", "selection_constraint_reason": "杯架位安装限制",
        "tag_expression": {"any_of": [{"all_of": [{"dimension": "安装位", "values": ["cup_holder"]}]}]},
        "scoring": {"score": 76, "components": {key: 75 for key in report.COMPONENTS}},
        "selected": True, "rank": 1, "round1_rank": 2, "selection_note": "头部压力较低",
        "primary_poe": {"primary_row_number": 8, "metrics": {"average_price_90d": 20, "click_conversion_rate_90d": 8.33}},
        "product_metrics": {"matched_asin_count": 15, "monthly_sales_known_sum": 3000},
        "keyword_metrics": {"direct_assignment_count": 2},
        "search_growth_evidence": {"growth_rates": {"搜索量增长率-近90天 (%)": -.5, "搜索量增长率-近180天 (%)": .87, "搜索量增长率-近360天 (%)": 15}},
        "ad_cost_evidence": {"representative_bid": 1.4, "pressure_estimate": 84, "mean_price": 20,
            "click_conversion_rate": 1/12, "half_conversion_pressure_estimate": 168,
            "search_coverage": .9, "core_keyword_count": 2, "conversion_keyword_count": 2,
            "participating_keyword_count": 2, "missing_bid_count": 0, "total_clicks": 1200,
            "total_purchases": 100, "conversion_match_rate": 1, "purchase_coverage": 1, "click_coverage": 1,
            "keyword_details": [
                {"keyword": "cup phone holder", "clicks": 800, "purchases": 80, "ppc_bid": 1,
                 "purchase_weight": .8, "weighted_bid": .8, "included": True,
                 "period": "2026-06-01/2026-08-29", "bid_source_rows": [102], "conversion_source_rows": [12]},
                {"keyword": "cup phone mount", "clicks": 400, "purchases": 20, "ppc_bid": 3,
                 "purchase_weight": .2, "weighted_bid": .6, "included": True,
                 "period": "2026-06-01/2026-08-29", "bid_source_rows": [103], "conversion_source_rows": [13]},
            ]},
        "refined_product_evidence": {"effective_count": 15, "total_monthly_sales": 3000,
            "mean_price": 20, "product_head_share_pct": 33, "brand_head_share_pct": 40,
            "new_product_count": 5, "successful_new_product_count": 2, "confidence": "low"},
        "top20": [{"asin": "B012345678", "title": "Car mount", "price": 20, "monthly_sales": 100,
                   "brand": "A", "month": "2026-07", "product_url": "https://www.amazon.com/dp/B012345678"}],
        "keyword_assignments": [{"keyword": "cup phone holder", "type": "direct", "reason": "杯架明确需求",
            "main_source_rows": [{"row_number": 2, "fields": {"月搜索量": 10000, "PPC竞价": "$1.00"}}]}],
        "rule_conclusions": {"status": "ready", "confidence": "low", "sample_count": 15, "mean_price": 20,
            "rules": {key: {"status": "ready", "label": label, "value": 30,
                "level": "较低", "basis": "仅本市场样本", "summary": "基于本市场数据计算"}
                for key, label in zip(report.RULES, report.RULE_LABELS)},
            "pivots": {"price": {"bands": [{"label": "0.8–1.0 倍均价", "listing_count": 10,
                "listing_count_share": 66.66, "sales": 2500, "sales_share": 83.33, "avg_sales": 250}]}}},
    }


def result(items: list[dict] | None = None, selected: list[str] | None = None) -> dict:
    items = [candidate()] if items is None else items
    return {"run_id": "test-run-1", "rule_version": "two-round-test", "candidates": items,
            "selected_candidate_ids": [item["id"] for item in items] if selected is None else selected}


class TwoRoundReportTests(unittest.TestCase):
    def test_source_preserved_byte_for_byte(self):
        rendered = report.render_report(BASE, result())
        self.assertEqual(report._strip_owned(rendered), BASE)
        self.assertLess(rendered.index("NICHE_TWO_ROUND_START"), rendered.index('<h2 id="small">'))
        self.assertGreater(rendered.index("NICHE_TWO_ROUND_START"), rendered.index("</svg></details>"))
        self.assertIn("<svg viewBox=\"0 0 1 1\"><path d=\"M0 0\"/></svg>", rendered)

    def test_idempotence_and_transition_to_refinement(self):
        short = result()
        first = report.render_report(BASE, short)
        self.assertEqual(report.render_report(first, short), first)
        refined = report.render_report(first, short, result())
        self.assertEqual(report.render_report(refined, short, result()), refined)
        self.assertEqual(refined.count("<!-- NICHE_TWO_ROUND_START -->"), 1)
        self.assertEqual(refined.count("<!-- NICHE_TWO_ROUND_STYLE_START -->"), 1)
        self.assertEqual(report._strip_owned(refined), BASE)

    def test_shortlist_does_not_claim_final_results(self):
        rendered = report.render_report(BASE, result())
        self.assertIn("等待关键词级转化表", rendered)
        self.assertIn("补表后将分别计算", rendered)
        self.assertIn("供需指数（80%）", rendered)
        self.assertIn("退货率仅作风险提示", rendered)
        self.assertNotIn('id="niche-final-top3"', rendered)
        self.assertNotIn("本细分市场的八项结论", rendered)
        self.assertNotIn("84.00%", rendered[rendered.index('id="niche-awaiting-conversion"'):])

    def test_refined_cohort_metrics_and_all_eight_rules(self):
        rendered = report.render_report(BASE, result(), result())
        self.assertIn('id="niche-final-top3"', rendered)
        self.assertIn("不重新评分或更改 Top3", rendered)
        for expected in ("1.4000", "8.33%", "84.00%", "168.00%", "80.00%", "0.8000", "0.6000", "0.87%", "-0.50%", "83.33%"):
            self.assertIn(expected, rendered)
        for label in report.RULE_LABELS:
            self.assertIn(label, rendered)
        self.assertIn("仅本市场样本", rendered)
        self.assertIn("低置信度（有效商品少于 50 个）", rendered)

    def test_refinement_report_uses_the_fixed_competition_layout(self):
        rendered = report.render_report(BASE, result(), result())
        self.assertIn('data-layout-version="two-round-competition-v1"', rendered)
        self.assertIn('id="niche-two-round-competition-style"', rendered)
        self.assertIn('id="niche-two-round-pivot-script"', rendered)
        self.assertNotIn('niche-competition-environment-script', rendered)
        self.assertLess(rendered.index('id="niche-shortlist"'), rendered.index('id="niche-refinement"'))
        self.assertLess(rendered.index('id="niche-refinement"'), rendered.index('id="niche-final-top3"'))
        expected_headers = (
            '<th scope="col">细分市场</th><th scope="col">核心词数</th><th scope="col">参与词数</th>'
            '<th scope="col">商品均价</th><th scope="col">加权CPC</th><th scope="col">90天转化率</th><th scope="col">广告压力</th>'
        )
        self.assertIn(expected_headers, rendered)
        for label in ("细分市场竞争环境分析", "市场规模", "价格与获客", "竞争集中", "进入窗口", "8 项规则结论", "基础维度透视"):
            self.assertIn(label, rendered)
        for pivot in ("review", "launch", "rating", "price"):
            self.assertIn(f'data-ntr-pivot="{pivot}"', rendered)
        self.assertIn('#niche-refinement th,#niche-refinement td{box-sizing:border-box;border:1px solid #d7e2ee}', rendered)
        self.assertIn('#niche-refinement th:not(:first-child),#niche-refinement td:not(:first-child){width:13%;text-align:center;white-space:nowrap}', rendered)
        self.assertNotIn('<div class="ntr-formula">', rendered)

    def test_refinement_rejects_any_candidate_or_order_outside_frozen_top3(self):
        rejected = candidate("truck")
        rejected.update(name="卡车固定手机", selection_note="与杯架候选重叠", scoring_issues=["缺少有效竞价"])
        refinement = result([candidate(), rejected], ["cup"])
        with self.assertRaises(ValueError):
            report.render_report(BASE, result([candidate(), rejected]), refinement)

    def test_keyword_period_and_two_sources_are_displayed_separately(self):
        rendered = report._keyword_rows(candidate(), refined=True)
        for heading in ("转化统计周期", "卖家精灵竞价来源行", "新商机表转化来源行"):
            self.assertIn(heading, rendered)
        self.assertIn("<td>cup phone holder</td><td>2026-06-01/2026-08-29</td>", rendered)
        self.assertIn("<td>[102]</td><td>[12]</td>", rendered)
        self.assertIn("<td>[103]</td><td>[13]</td>", rendered)

    def test_missing_bid_source_never_borrows_conversion_source(self):
        item = candidate()
        item["ad_cost_evidence"]["keyword_details"][0].pop("bid_source_rows")
        rendered = report._keyword_rows(item, refined=True)
        self.assertIn("<td>未提供</td><td>[12]</td>", rendered)
        self.assertNotIn("<td>[12]</td><td>[12]</td>", rendered)

    def test_equal_priority_note_is_visible_in_ranking_and_selected_card(self):
        item = candidate()
        item["selection_note"] = "同优先级：卡车固定手机"
        self.assertIn(item["selection_note"], report._score_table(result([item])))
        self.assertIn(item["selection_note"], report._candidate_card(item, 1, refined=True))

    def test_dynamic_text_and_urls_are_escaped(self):
        item = candidate()
        attack = '<script>alert("x")</script>'
        item.update(name=attack, definition=attack, selection_note=attack)
        item["top20"][0].update(title=attack, product_url="javascript:alert(1)", asin=attack)
        item["keyword_assignments"][0]["keyword"] = attack
        item["ad_cost_evidence"]["keyword_details"][0]["exclusion_reason"] = attack
        item["rule_conclusions"]["rules"]["ad_pressure"]["basis"] = attack
        short = result([item])
        short["run_id"] = '\" onmouseover="alert(1)'
        rendered = report.render_report(BASE, short, result([item]))
        self.assertEqual(1, rendered.count('<script id="niche-two-round-copy-script">'))
        self.assertNotIn('href="javascript:', rendered)
        self.assertNotIn('data-shortlist-run-id="" onmouseover=', rendered)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn("&quot; onmouseover=&quot;", rendered)

    def test_safe_https_link_and_control_char_rejection(self):
        self.assertIsNone(report._safe_link("https://example.com/\njavascript:x"))
        self.assertIsNone(report._safe_link("//example.com"))
        self.assertIsNone(report._safe_link("https://user:pass@example.com"))
        self.assertEqual(report._safe_link('https://example.com/?x="hi"&y=1'), "https://example.com/?x=&quot;hi&quot;&amp;y=1")

    def test_only_explicit_legacy_extension_is_removed(self):
        old = BASE.replace('</head>', '<style id="niche-top3-style">#niche-top3{color:red}</style></head>')
        old = old.replace('<a href="#small">', '<a href="#niche-top3" data-niche-top3-nav="true">Old Top 3</a><a href="#small">')
        old = old.replace('<h2 id="small">', '<!-- NICHE_TOP3_START --><section id="niche-top3">obsolete</section><!-- NICHE_TOP3_END --><h2 id="small">')
        rendered = report.render_report(old, result())
        self.assertNotIn("obsolete", rendered)
        self.assertNotIn("niche-top3-style", rendered)
        self.assertEqual(report._strip_owned(rendered), BASE)

    def test_empty_or_reordered_refinement_is_rejected(self):
        with self.assertRaises(ValueError):
            report.render_report(BASE, result(), result([candidate()], []))

    def test_invalid_binding_and_missing_anchor_fail(self):
        with self.assertRaises(ValueError):
            report.render_report(BASE, result(), result([candidate("outside")]))
        with self.assertRaises(ValueError):
            report.render_report(BASE.replace('id="small"', 'id="changed"'), result())
        with self.assertRaises(ValueError):
            report.render_report(BASE, result(selected=["cup", "cup"]))

    def test_missing_values_are_not_displayed_as_zero(self):
        item = candidate()
        item["scoring"] = {"score": None, "components": {}}
        item["ad_cost_evidence"] = {"representative_bid": None, "pressure_estimate": None}
        item["rule_conclusions"] = {}
        rendered = report.render_report(BASE, result([item]), result([item]))
        self.assertIn("待验证", rendered)
        self.assertIn("加权CPC 未提供", rendered)
        self.assertIn("广告压力 ACOS 未提供", rendered)

    def test_supply_and_risk_evidence_are_rendered_without_initial_advertising(self):
        item = candidate()
        item["supply_demand_evidence"] = {
            "status": "available", "supply_demand_index": 2, "supply_demand_score": 100,
            "listing_count_share": .1, "listing_sales_share": .2,
            "category_valid_asin_count": 1000, "category_monthly_sales_sum": 100000,
        }
        item["return_risk_context"] = {"status": "available", "return_rate_360d": 4}
        rendered = report._candidate_card(item, 1, refined=False)
        for text in ("供需指数 <strong>2.0000</strong>", "Listing 数量占比 10.00%", "销量占比 20.00%", "退货率 4.00%"):
            self.assertIn(text, rendered)
        self.assertNotIn("广告成本压力估算", rendered)

    def test_top20_copy_control_keeps_only_asins_in_rank_order(self):
        item = candidate()
        item["top20"] = [
            {"asin": "B000000001", "title": "one"},
            {"asin": "B000000002", "title": "two"},
        ]
        rendered = report._top20(item)
        self.assertIn('data-count="2"', rendered)
        self.assertIn("一键复制这 2 个 ASIN", rendered)
        self.assertIn("B000000001\nB000000002", rendered)
        self.assertNotIn("one\ntwo", rendered)
        empty = candidate()
        empty["top20"] = []
        self.assertIn("disabled", report._top20(empty))


if __name__ == "__main__":
    unittest.main()
