import importlib.util
import math
import pathlib
import unittest

MODULE = pathlib.Path(__file__).resolve().parents[1] / "tools" / "niche_refinement_metrics.py"
spec = importlib.util.spec_from_file_location("niche_refinement_metrics", MODULE)
metrics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(metrics)


def keyword(name, purchases, clicks, bid, **extra):
    return dict(keyword=name, key=name, purchases=purchases, clicks=clicks,
                ppc_bid=bid, conversion_available=True, **extra)


def products(count=10):
    return [dict(asin=f"A{i:09d}", brand=f"Brand {i}", price=10+i,
                 monthly_sales=100 if i == 0 else 10-i,
                 launch_days=360 if i == 0 else 359 if i == 2 else 500,
                 review_count=i*100, rating=4+i/10) for i in range(count)]


class AdvertisingEvidenceTests(unittest.TestCase):
    def test_full_conversion_formula_uses_click_weighted_cpc(self):
        evidence = metrics.advertising_evidence([
            keyword("cup holder phone mount", 80, 800, 1, source_row=2),
            keyword("phone holder cup holder", 20, 400, 3, source_row=3),
        ], 20)
        self.assertEqual(evidence["status"], "ready")
        self.assertAlmostEqual(evidence["representative_bid"], 5/3)
        self.assertAlmostEqual(evidence["click_conversion_rate"], 100/1200)
        self.assertAlmostEqual(evidence["pressure_estimate"], 100)
        self.assertAlmostEqual(evidence["half_conversion_pressure_estimate"], 200)
        self.assertEqual(evidence["purchase_coverage"], 1)
        self.assertAlmostEqual(evidence["keyword_details"][0]["click_weight"], 2/3)
        self.assertAlmostEqual(evidence["keyword_details"][0]["weighted_bid"], 2/3)
        self.assertEqual(evidence["keyword_details"][0]["source_row"], 2)

    def test_zero_purchase_word_keeps_clicks(self):
        evidence = metrics.advertising_evidence([
            keyword("cup mount", 100, 1000, 2),
            keyword("cup phone holder", 0, 1000, 9),
        ], 20)
        self.assertEqual(evidence["participating_keyword_count"], 2)
        self.assertEqual(evidence["total_clicks"], 2000)
        self.assertEqual(evidence["representative_bid"], 5.5)
        self.assertAlmostEqual(evidence["keyword_details"][1]["click_weight"], .5)
        self.assertEqual(evidence["pressure_estimate"], 550)

    def test_keyword_missing_bid_is_dropped_from_conversion_and_cpc(self):
        # user decision 2026-10-03: one paired keyword set for both the conversion rate and the CPC
        evidence = metrics.advertising_evidence([
            keyword("cup mount", 70, 700, 2),
            keyword("cup phone holder", 30, 300, None),
        ], 20)
        self.assertEqual(evidence["status"], "ready")
        self.assertEqual(evidence["total_purchases"], 70)
        self.assertEqual(evidence["total_clicks"], 700)
        self.assertAlmostEqual(evidence["click_conversion_rate"], .1)
        self.assertAlmostEqual(evidence["representative_bid"], 2)
        self.assertEqual(evidence["purchase_coverage"], .7)
        self.assertEqual(evidence["click_coverage"], .7)
        self.assertEqual(evidence["missing_bid_count"], 1)
        self.assertAlmostEqual(evidence["pressure_estimate"], 100)
        self.assertFalse(evidence["keyword_details"][1]["included"])

    def test_keyword_missing_conversion_is_dropped_even_with_bid(self):
        evidence = metrics.advertising_evidence([
            keyword("cup mount", 50, 500, 2),
            keyword("cup phone holder", None, None, 5),
            keyword("zero click word", 0, 0, 9),
        ], 20)
        self.assertEqual(evidence["participating_keyword_count"], 1)
        self.assertAlmostEqual(evidence["representative_bid"], 2)
        self.assertAlmostEqual(evidence["click_conversion_rate"], .1)
        self.assertIn("missing_or_invalid_conversion_data", evidence["keyword_details"][1]["exclusion_reason"])
        self.assertIn("missing_or_invalid_conversion_data", evidence["keyword_details"][2]["exclusion_reason"])

    def test_no_paired_keyword_means_ad_pressure_unknown(self):
        evidence = metrics.advertising_evidence([keyword("a", 5, 50, None), keyword("b", None, None, 2)], 20)
        self.assertEqual("pending_validation", evidence["status"])
        self.assertIn("no_keywords_with_both_conversion_and_bid", evidence["reasons"])
        self.assertIsNone(evidence["pressure_estimate"])

    def test_bid_conflict_preserves_conversion_coverage_denominator(self):
        rows = [keyword("cup mount", 60, 600, 2),
                keyword("cup holder", 40, 400, None, exclusion_reason="missing_bid")]
        evidence = metrics.advertising_evidence(rows, 20)
        self.assertEqual(evidence["all_conversion_purchases"], 100)
        self.assertEqual(evidence["all_conversion_clicks"], 1000)
        self.assertEqual(evidence["purchase_coverage"], .6)
        self.assertEqual(evidence["status"], "ready")

    def test_80_percent_coverage_is_accepted(self):
        evidence = metrics.advertising_evidence([
            keyword("cup mount", 80, 800, 2),
            keyword("cup phone holder", 20, 100, 0),
        ], 20)
        self.assertEqual(evidence["status"], "ready")
        self.assertEqual(evidence["purchase_coverage"], .8)
        self.assertAlmostEqual(evidence["click_conversion_rate"], 80 / 800)

    def test_conversion_missing_does_not_enter_coverage_denominator(self):
        row = keyword("cup phone holder", 9999, 99999, 0.01)
        row["conversion_available"] = False
        evidence = metrics.advertising_evidence([keyword("cup mount", 10, 100, 2), row], 20)
        self.assertEqual(evidence["all_conversion_purchases"], 10)
        self.assertEqual(evidence["conversion_match_rate"], .5)
        self.assertEqual(evidence["representative_bid"], 2)

    def test_nonfinite_and_zero_totals_are_unknown(self):
        for bid in [None, 0, -1, float("inf"), float("nan")]:
            evidence = metrics.advertising_evidence([keyword("cup mount", 10, 100, bid)], 20)
            self.assertEqual(evidence["status"], "pending_validation")
            self.assertIsNone(evidence["pressure_estimate"])
        evidence = metrics.advertising_evidence([keyword("cup mount", 0, 100, 1)], 20)
        self.assertEqual(evidence["representative_bid"], 1)
        self.assertIsNone(evidence["pressure_estimate"])
        self.assertEqual(evidence["total_clicks"], 100)

    def test_full_conversion_rows_are_not_deduplicated(self):
        row = keyword("Cup Mount", 10, 100, 2)
        evidence = metrics.advertising_evidence([row, dict(row)], 20)
        self.assertEqual(evidence["total_purchases"], 20)
        conflict = dict(row, purchases=20)
        evidence = metrics.advertising_evidence([row, conflict], 20)
        self.assertEqual(evidence["total_purchases"], 30)
        self.assertEqual(evidence["conversion_keyword_count"], 2)

    def test_each_full_conversion_row_contributes_its_click_weight(self):
        row = keyword("cup holder", 40, 400, 2)
        rows = [keyword("cup mount", 60, 600, 2), row, dict(row, ppc_bid=3)]
        evidence = metrics.advertising_evidence(rows, 20)
        self.assertEqual(evidence["all_conversion_purchases"], 140)
        self.assertEqual(evidence["total_purchases"], 140)
        self.assertEqual(evidence["core_keyword_count"], 3)
        self.assertAlmostEqual(evidence["representative_bid"], 16/7)

    def test_unrelated_poe_bid_columns_do_not_change_calculation(self):
        row = keyword("cup mount", 10, 100, 2)
        before = metrics.advertising_evidence([row], 20)
        row.update(poe_recommended_bid=0.001, poe_maximum_bid=999, poe_minimum_bid=-5)
        after = metrics.advertising_evidence([row], 20)
        self.assertEqual(before["pressure_estimate"], after["pressure_estimate"])
        row["ppc_bid"] = 4
        changed = metrics.advertising_evidence([row], 20)
        self.assertEqual(changed["pressure_estimate"], 2*before["pressure_estimate"])


class ProductEvidenceTests(unittest.TestCase):
    def test_mean_head_shares_and_new_product_definition(self):
        evidence = metrics.product_evidence(products())
        self.assertEqual(evidence["effective_count"], 10)
        self.assertEqual(evidence["mean_price"], 14.5)
        self.assertEqual(evidence["total_monthly_sales"], 145)
        self.assertEqual(evidence["product_head_count"], 1)
        self.assertAlmostEqual(evidence["product_head_share_pct"], 100/145*100)
        self.assertEqual(evidence["brand_head_share_pct"], evidence["product_head_share_pct"])
        self.assertEqual(evidence["new_product_count"], 2)
        self.assertEqual(evidence["successful_new_product_count"], 1)
        self.assertEqual(evidence["new_product_success_rate"], .5)
        self.assertEqual(evidence["confidence"], "low")

    def test_head_count_rounds_up_and_ties_are_stable(self):
        rows = [dict(asin=f"A{i:09d}", brand=f"Brand {i:02d}", price=20,
                     monthly_sales=10, launch_days=1, review_count=1, rating=4.5) for i in range(11)]
        evidence = metrics.product_evidence(list(reversed(rows)))
        self.assertEqual(evidence["product_head_count"], 2)
        self.assertEqual(evidence["brand_head_count"], 2)
        self.assertEqual(evidence["success_head_count"], 3)
        self.assertEqual(evidence["product_head_asins"], ["A000000000", "A000000001"])
        self.assertEqual(evidence["brand_head_names"], ["Brand 00", "Brand 01"])

    def test_brand_aggregation_normalizes_case_and_whitespace(self):
        rows = products()
        rows[0]["brand"] = "  Alpha   Mount  "
        rows[1]["brand"] = "alpha mount"
        evidence = metrics.product_evidence(rows)
        self.assertEqual(evidence["brand_count"], 9)
        self.assertAlmostEqual(evidence["brand_head_share_pct"], 109/145*100)
        self.assertEqual(evidence["brand_head_keys"], ["alpha mount"])
        self.assertEqual(evidence["brand_head_names"], ["Alpha Mount"])
        self.assertEqual(evidence["members"][0]["brand_original"], "  Alpha   Mount  ")

    def test_unknown_brand_values_are_missing(self):
        for brand in ("unknown", "未知", "NA", "N/A", " Not   Provided "):
            rows = products()
            rows[0]["brand"] = brand
            evidence = metrics.product_evidence(rows)
            self.assertEqual(evidence["brand_missing_count"], 1)
            self.assertEqual(evidence["brand_status"], "pending_validation")
            self.assertIsNone(evidence["brand_head_share_pct"])

    def test_incomplete_fields_are_not_zero_imputed(self):
        rows = products()
        rows[0].update(launch_days=None, brand=None, review_count=None, rating=None)
        evidence = metrics.product_evidence(rows)
        self.assertIsNone(evidence["brand_head_share_pct"])
        self.assertIsNone(evidence["new_product_success_rate"])
        self.assertIsNotNone(evidence["product_head_share_pct"])
        self.assertEqual(evidence["effective_count"], 10)
        self.assertEqual(evidence["launch_days_missing_count"], 1)

    def test_invalid_and_duplicate_products_do_not_expand_market(self):
        rows = products()
        evidence = metrics.product_evidence(rows+[dict(rows[0]), dict(rows[1], price=0), dict(rows[2], asin="")])
        self.assertEqual(evidence["effective_count"], 10)
        self.assertEqual(evidence["duplicates_removed"], 1)
        self.assertEqual(len(evidence["excluded_products"]), 2)
        evidence = metrics.product_evidence(rows+[dict(rows[0], monthly_sales=20)])
        self.assertEqual(evidence["effective_count"], 9)
        self.assertNotIn(rows[0]["asin"], evidence["top20_asins"])


class EightConclusionTests(unittest.TestCase):
    def test_concentration_price_and_ad_are_consistent_with_second_round(self):
        rows = products()
        evidence = metrics.product_evidence(rows)
        ad = metrics.advertising_evidence([keyword("cup mount", 10, 100, 2)], evidence["mean_price"])
        result = metrics.eight_conclusions(rows, ad)
        self.assertEqual(len(result["rules"]), 8)
        self.assertEqual(result["mean_price"], evidence["mean_price"])
        self.assertEqual(result["rules"]["product_monopoly"]["value"], evidence["product_head_share_pct"])
        self.assertEqual(result["rules"]["brand_monopoly"]["value"], evidence["brand_head_share_pct"])
        self.assertEqual(result["rules"]["ad_pressure"]["value"], ad["pressure_estimate"])
        self.assertEqual(result["rules"]["price_sensitivity"]["value"], 100/145*100)
        self.assertEqual(result["rules"]["review_dependency"]["value"], 1/145*100)

    def test_price_bins_use_segment_mean_and_merge_small_tail(self):
        rows = []
        for i in range(25):
            price, sales = (10, 5) if i < 10 else (20, 15) if i < 20 else (30, 1)
            rows.append(dict(asin=f"A{i:09d}", brand="One", price=price, monthly_sales=sales,
                             launch_days=30 if i < 10 else 400,
                             rating=4.0 if i < 10 else 4.8, review_count=i*50))
        result = metrics.eight_conclusions(rows, {"pressure_estimate":84, "status":"ready"})
        self.assertEqual(result["mean_price"], 18)
        bands = result["pivots"]["price"]["bands"]
        self.assertEqual([band["listing_count"] for band in bands], [10,15])
        self.assertAlmostEqual(bands[0]["actual_price_high"], 10.8)
        self.assertEqual(sum(band["listing_count"] for band in bands), 25)
        self.assertAlmostEqual(sum(band["sales_share"] for band in bands), 100)
        selected = result["rules"]["best_price_bands"]["selected_bands"]
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["listing_count"], 15)
        self.assertGreater(selected[0]["sales_share"], selected[0]["listing_count_share"])
        self.assertEqual(result["rules"]["ad_pressure"]["level"], "很高")

    def test_missing_fields_keep_independent_rules_available(self):
        rows = products()
        rows[0].update(review_count=None, rating=None, launch_days=None)
        result = metrics.eight_conclusions(rows, {"pressure_estimate":84, "status":"ready"})
        for key in ("review_dependency", "rating_requirement", "new_product_cycle"):
            self.assertEqual(result["rules"][key]["status"], "pending_validation")
            self.assertIsNone(result["rules"][key]["value"])
        self.assertEqual(result["rules"]["product_monopoly"]["status"], "ready")
        self.assertEqual(result["rules"]["ad_pressure"]["value"], 84)

    def test_no_qualifying_band_is_unknown_and_not_category_fallback(self):
        rows = products()
        for row in rows:
            row.update(monthly_sales=1, rating=4.5, price=20, launch_days=100)
        result = metrics.eight_conclusions(rows, {"pressure_estimate":84, "status":"ready"})
        for key in ("rating_requirement", "new_product_cycle", "best_price_bands"):
            self.assertEqual(result["rules"][key]["reason"], "no_qualifying_band")
            self.assertIsNone(result["rules"][key]["value"])

    def test_no_effective_products_does_not_crash(self):
        result = metrics.eight_conclusions([], {})
        self.assertEqual(result["sample_count"], 0)
        self.assertIsNone(result["mean_price"])
        self.assertTrue(all(row["status"] == "pending_validation" for row in result["rules"].values()))


if __name__ == "__main__":
    unittest.main()
