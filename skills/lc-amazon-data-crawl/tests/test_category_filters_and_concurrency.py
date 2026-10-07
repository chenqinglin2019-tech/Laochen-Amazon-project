from __future__ import annotations

import json
import copy
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import amazon_category_rank_crawler as category


class SubcategoryBsrTests(unittest.TestCase):
    def test_zero_one_and_multiple_rank_semantics(self) -> None:
        self.assertEqual(category.parse_subcategory_bsr_ranks("no rank here"), [])
        self.assertEqual(
            category.parse_subcategory_bsr_ranks("#130 in Fruit Bowls 近30天销量(父体): 29"),
            [{"rank": 130, "category_name": "Fruit Bowls"}],
        )
        self.assertEqual(
            category.parse_subcategory_bsr_ranks(
                "#48,598 in Kitchen & Dining #130 in Fruit Bowls "
                "#25 in Serving Bowls FBA费用: $6.31"
            ),
            [
                {"rank": 130, "category_name": "Fruit Bowls"},
                {"rank": 25, "category_name": "Serving Bowls"},
            ],
        )

    def test_format_is_derived_from_structured_contract(self) -> None:
        value = [
            {"rank": 130, "category_name": "Fruit Bowls"},
            {"rank": 2500, "category_name": "Serving Bowls"},
        ]
        self.assertEqual(
            category.format_subcategory_bsr_ranks(value),
            "#130 in Fruit Bowls ; #2,500 in Serving Bowls",
        )

    @unittest.skipIf(category.Workbook is None, "openpyxl is unavailable")
    def test_excel_rank_column_is_wide_enough_for_formatted_values(self) -> None:
        workbook = category.Workbook()
        sheet = workbook.active
        category.write_sheet(
            sheet,
            ["ASIN", "子类目节点排名"],
            [{
                "asin": "B000000001",
                "subcategory_bsr_ranks": [
                    {"rank": 11638, "category_name": "Women's Yoga Leggings"}
                ],
            }],
        )
        self.assertEqual(sheet["B2"].value, "#11,638 in Women's Yoga Leggings")
        self.assertGreaterEqual(sheet.column_dimensions["B"].width, 42)

    def test_dedup_keeps_first_complete_rank_pair_per_category(self) -> None:
        rows = category.build_dedup_rows(
            [
                {
                    "asin": "B000000001",
                    "category_path": "A",
                    "subcategory_bsr_ranks": [
                        {"rank": 130, "category_name": "Fruit Bowls"}
                    ],
                },
                {
                    "asin": "B000000001",
                    "category_path": "B",
                    "subcategory_bsr_ranks": [
                        {"rank": 999, "category_name": "Fruit Bowls"},
                        {"rank": 25, "category_name": "Serving Bowls"},
                    ],
                },
            ]
        )
        self.assertEqual(
            rows[0]["subcategory_bsr_ranks"],
            [
                {"rank": 130, "category_name": "Fruit Bowls"},
                {"rank": 25, "category_name": "Serving Bowls"},
            ],
        )


class ProductFilterTests(unittest.TestCase):
    def test_fulfillment_evidence_does_not_hide_unknown_values(self) -> None:
        self.assertEqual(
            category.parse_fulfillment_evidence("配送: FBA"),
            ("FBA", "FBA"),
        )
        self.assertEqual(
            category.parse_fulfillment_evidence("配送: SFP"),
            ("", "SFP"),
        )
        self.assertEqual(
            category.parse_fulfillment_evidence("配送: 卖家配送"),
            ("", "卖家配送"),
        )
        self.assertEqual(category.parse_fulfillment_evidence("FBA费用: $6.31"), ("", ""))
        self.assertEqual(category.parse_fulfillment_evidence("配送时长: 3天"), ("", ""))
        self.assertEqual(category.parse_fulfillment_evidence("配送费: $3.00"), ("", ""))
        self.assertEqual(category.parse_fulfillment_evidence("non-FBA"), ("", ""))
        self.assertEqual(category.parse_fulfillment_evidence("FBA"), ("", ""))
        self.assertEqual(category.parse_fulfillment_evidence("FBM"), ("", ""))
        self.assertEqual(category.parse_fulfillment_evidence("AMZ"), ("", ""))
        self.assertEqual(
            category.parse_fulfillment_evidence("Seller Fulfilled Prime", explicit_value=True),
            ("", "Seller Fulfilled Prime"),
        )
        self.assertEqual(
            category.parse_fulfillment_evidence("配送: FBM", explicit_value=True),
            ("FBM", "FBM"),
        )

    def test_fulfillment_evidence_recognizes_known_value_at_field_boundary(self) -> None:
        self.assertEqual(
            category.parse_fulfillment_evidence("配送:FBM卖家:1"),
            ("FBM", "FBM卖家"),
        )
        self.assertEqual(
            category.parse_fulfillment_evidence("配送方式：FBA品牌：Generic"),
            ("FBA", "FBA品牌"),
        )
        self.assertEqual(
            category.parse_fulfillment_evidence("Fulfillment Method: AMZ Seller: Amazon"),
            ("AMZ", "AMZ Seller"),
        )
        self.assertEqual(
            category.parse_fulfillment_evidence("FBM卖家:1", explicit_value=True),
            ("FBM", "FBM卖家:1"),
        )

    def test_fulfillment_known_prefix_accepts_any_suffix_in_explicit_context(self) -> None:
        self.assertEqual(
            category.parse_fulfillment_evidence("配送:FBMPlus"),
            ("FBM", "FBMPlus"),
        )
        self.assertEqual(
            category.parse_fulfillment_evidence("配送:FBA费用:$6.31"),
            ("FBA", "FBA费用"),
        )
        self.assertEqual(
            category.parse_fulfillment_evidence("non-FBA", explicit_value=True),
            ("", "non-FBA"),
        )
        self.assertEqual(
            category.parse_fulfillment_evidence("配送: FBA Fee:$6"),
            ("FBA", "FBA Fee"),
        )
        self.assertEqual(
            category.parse_fulfillment_evidence("FBA Fee", explicit_value=True),
            ("FBA", "FBA Fee"),
        )
        self.assertEqual(
            category.parse_fulfillment_evidence("配送: FBM Plus"),
            ("FBM", "FBM Plus"),
        )
        self.assertEqual(
            category.parse_fulfillment_evidence("FBM Plus", explicit_value=True),
            ("FBM", "FBM Plus"),
        )
        self.assertEqual(category.parse_fulfillment_evidence("FBA费用: $6.31"), ("", ""))

    def test_filter_allows_only_configured_or_genuinely_missing_fulfillment(self) -> None:
        filters = category.ProductFilterConfig(
            allowed_fulfillment_methods=("FBM",),
            allow_missing_fulfillment=True,
            require_subcategory_rank=True,
        )
        rank = [{"rank": 130, "category_name": "Fruit Bowls"}]
        rows = [
            {
                "asin": "FBM",
                "fulfillment_method": "FBM",
                "fulfillment_method_raw": "FBM",
                "subcategory_bsr_ranks": rank,
            },
            {
                "asin": "MISSING",
                "fulfillment_method": "",
                "fulfillment_method_raw": "",
                "subcategory_bsr_ranks": rank,
            },
            {
                "asin": "UNKNOWN",
                "fulfillment_method": "",
                "fulfillment_method_raw": "SFP",
                "subcategory_bsr_ranks": rank,
            },
            {
                "asin": "AMZ",
                "fulfillment_method": "AMZ",
                "fulfillment_method_raw": "AMZ",
                "subcategory_bsr_ranks": rank,
            },
            {
                "asin": "CHINESE_UNKNOWN",
                "fulfillment_method": "",
                "fulfillment_method_raw": "卖家配送",
                "subcategory_bsr_ranks": rank,
            },
            {
                "asin": "NO_RANK",
                "fulfillment_method": "FBM",
                "fulfillment_method_raw": "FBM",
                "subcategory_bsr_ranks": [],
            },
        ]
        accepted, counts = category.filter_product_records(rows, filters)
        self.assertEqual([row["asin"] for row in accepted], ["FBM", "MISSING"])
        self.assertEqual(counts["fulfillment_method_not_allowed"], 3)
        self.assertEqual(counts["subcategory_bsr_rank_missing"], 1)

    def test_fulfillment_denylist_keeps_every_ranked_non_fba_record(self) -> None:
        filters = category.ProductFilterConfig(
            excluded_fulfillment_methods=("FBA",),
            require_subcategory_rank=True,
        )
        rank = [{"rank": 130, "category_name": "Fruit Bowls"}]
        rows = [
            {
                "asin": "FBA",
                "fulfillment_method": "FBA",
                "fulfillment_method_raw": "FBA卖家",
                "subcategory_bsr_ranks": rank,
            },
            {
                "asin": "RAW_FBA",
                "fulfillment_method": "",
                "fulfillment_method_raw": "FBA卖家:1",
                "subcategory_bsr_ranks": rank,
            },
            {
                "asin": "FBM",
                "fulfillment_method": "FBM",
                "fulfillment_method_raw": "FBM卖家",
                "subcategory_bsr_ranks": rank,
            },
            {
                "asin": "AMZ",
                "fulfillment_method": "AMZ",
                "fulfillment_method_raw": "AMZ",
                "subcategory_bsr_ranks": rank,
            },
            {
                "asin": "MISSING",
                "fulfillment_method": "",
                "fulfillment_method_raw": "",
                "subcategory_bsr_ranks": rank,
            },
            {
                "asin": "UNKNOWN",
                "fulfillment_method": "",
                "fulfillment_method_raw": "SFP",
                "subcategory_bsr_ranks": rank,
            },
            {
                "asin": "RAW_FBA_FEE_PREFIX",
                "fulfillment_method": "",
                "fulfillment_method_raw": "FBA费用",
                "subcategory_bsr_ranks": rank,
            },
            {
                "asin": "NO_RANK",
                "fulfillment_method": "FBM",
                "fulfillment_method_raw": "FBM",
                "subcategory_bsr_ranks": [],
            },
        ]
        accepted, counts = category.filter_product_records(rows, filters)
        self.assertEqual(
            [row["asin"] for row in accepted],
            ["FBM", "AMZ", "MISSING", "UNKNOWN"],
        )
        self.assertEqual(counts["fulfillment_method_not_allowed"], 3)
        self.assertEqual(counts["subcategory_bsr_rank_missing"], 1)

    def test_config_defaults_validation_and_fingerprint_normalization(self) -> None:
        self.assertEqual(
            category.build_product_filter_config({}),
            category.ProductFilterConfig(),
        )
        first = category.build_product_filter_config(
            {
                "product_filters": {
                    "allowed_fulfillment_methods": ["fbm", "AMZ", "fbm"],
                    "allow_missing_fulfillment": True,
                    "require_subcategory_rank": True,
                }
            }
        )
        second = category.ProductFilterConfig(("AMZ", "FBM"), True, True)
        self.assertEqual(first, second)
        self.assertEqual(
            category.record_contract_fingerprint(first),
            category.record_contract_fingerprint(second),
        )
        self.assertNotEqual(
            category.record_contract_fingerprint(first),
            category.record_contract_fingerprint(category.ProductFilterConfig()),
        )
        self.assertEqual(
            category.SUBCATEGORY_BSR_SEMANTICS,
            {
                "single_row_is_child": True,
                "multiple_rows_skip_first": True,
                "preserve_all_children": True,
            },
        )
        self.assertEqual(category.FULFILLMENT_SEMANTICS["version"], 3)
        original_fingerprint = category.record_contract_fingerprint(first)
        with patch.object(
            category,
            "FULFILLMENT_SEMANTICS",
            dict(category.FULFILLMENT_SEMANTICS, version=4),
        ):
            self.assertNotEqual(
                original_fingerprint,
                category.record_contract_fingerprint(first),
            )
        with self.assertRaises(category.UserFacingError):
            category.build_product_filter_config(
                {"product_filters": {"allow_missing_fulfillment": "true"}}
            )
        with self.assertRaises(category.UserFacingError):
            category.build_product_filter_config(
                {"product_filters": {"unsupported": True}}
            )
        excluded = category.build_product_filter_config(
            {
                "product_filters": {
                    "excluded_fulfillment_methods": ["fba", "FBA"],
                    "require_subcategory_rank": True,
                }
            }
        )
        self.assertEqual(excluded.excluded_fulfillment_methods, ("FBA",))
        self.assertTrue(excluded.enabled)
        with self.assertRaises(category.UserFacingError):
            category.build_product_filter_config(
                {
                    "product_filters": {
                        "allowed_fulfillment_methods": ["FBM"],
                        "excluded_fulfillment_methods": ["FBA"],
                    }
                }
            )

    def test_resume_rejects_changed_record_contract_after_progress(self) -> None:
        state = {"completed_pages": ["page-1"], "record_contract_fingerprint": "old"}
        runtime = SimpleNamespace(record_contract_fingerprint="new")
        with self.assertRaises(category.UserFacingError):
            category.ensure_resume_record_contract_fingerprint(state, runtime)


class CategoryExtractionTests(unittest.TestCase):
    def test_empty_table_cell_keeps_fulfillment_column_alignment(self) -> None:
        parsed = category.parse_table_row_fields(
            {
                "headers": ["ASIN", "品牌", "配送方式"],
                "cells": ["B000000001", "", "FBM"],
                "text": "ASIN: B000000001 配送: FBM",
            }
        )
        self.assertEqual(parsed["fulfillment_method"], "FBM")
        self.assertEqual(parsed["fulfillment_method_raw"], "FBM")

    def test_strict_dom_extractors_propagate_browser_errors(self) -> None:
        driver = SimpleNamespace(
            execute_script=lambda *_args: (_ for _ in ()).throw(
                category.JavascriptException("script failed")
            )
        )
        self.assertEqual(category.extract_product_cards(driver), [])
        self.assertEqual(category.extract_table_rows(driver), [])
        with self.assertRaises(category.JavascriptException):
            category.extract_product_cards(driver, strict=True)
        with self.assertRaises(category.JavascriptException):
            category.extract_table_rows(driver, strict=True)
        with self.assertRaises(category.JavascriptException):
            category.find_next_page_url(driver, strict=True)

    def test_merge_preserves_unknown_fulfillment_raw_and_structured_child_rank(self) -> None:
        card = {
            "asin": "B000000001",
            "rank": "1",
            "title": "Test",
            "product_url": "https://www.amazon.com/dp/B000000001",
            "text": "ASIN: B000000001 FBA费用: $6.31",
        }
        row = {
            "asin": "B000000001",
            "headers": ["配送方式"],
            "cells": ["SFP"],
            "text": (
                "ASIN: B000000001 配送: SFP #48,598 in Kitchen & Dining "
                "#130 in Fruit Bowls 近30天销量(父体): 29"
            ),
        }
        runtime = SimpleNamespace(
            start_url="https://www.amazon.com/gp/new-releases/home-garden/1063238/",
            field_selectors={},
        )
        node = {
            "url": runtime.start_url,
            "name": "Kitchen",
            "path": ["Home", "Kitchen"],
            "node_id": "1063238",
        }
        with (
            patch.object(category, "extract_product_cards", return_value=[card]),
            patch.object(category, "extract_table_rows", return_value=[row]),
        ):
            records = category.merge_product_data(object(), runtime, node, 1, "ok")
        self.assertEqual(records[0]["fulfillment_method"], "")
        self.assertEqual(records[0]["fulfillment_method_raw"], "SFP")
        self.assertEqual(
            records[0]["subcategory_bsr_ranks"],
            [{"rank": 130, "category_name": "Fruit Bowls"}],
        )
        accepted, counts = category.filter_product_records(
            records,
            category.ProductFilterConfig(("FBM",), True, True),
        )
        self.assertEqual(accepted, [])
        self.assertEqual(counts, {"fulfillment_method_not_allowed": 1})

    def test_merge_uses_canonical_strength_then_source_priority(self) -> None:
        card = {
            "asin": "B000000001",
            "text": "ASIN: B000000001 配送: FBM卖家: 1",
        }
        row = {
            "asin": "B000000001",
            "headers": ["配送方式"],
            "cells": ["FBA"],
            "text": "ASIN: B000000001 配送: FBA",
        }
        runtime = SimpleNamespace(
            start_url="https://www.amazon.com/gp/new-releases/home-garden/1063238/",
            field_selectors={"fulfillment_method": [".fulfillment"]},
        )
        node = {"url": runtime.start_url, "name": "Kitchen", "path": ["Kitchen"]}
        with (
            patch.object(category, "extract_product_cards", return_value=[card]),
            patch.object(category, "extract_table_rows", return_value=[row]),
            patch.object(
                category,
                "extract_by_selectors",
                return_value={"fulfillment_method": "SFP"},
            ),
        ):
            record = category.merge_product_data(object(), runtime, node, 1, "ok")[0]
        self.assertEqual(record["fulfillment_method"], "FBA")
        self.assertEqual(record["fulfillment_method_raw"], "FBA")

        with (
            patch.object(category, "extract_product_cards", return_value=[card]),
            patch.object(category, "extract_table_rows", return_value=[row]),
            patch.object(
                category,
                "extract_by_selectors",
                return_value={"fulfillment_method": "AMZ"},
            ),
        ):
            record = category.merge_product_data(object(), runtime, node, 1, "ok")[0]
        self.assertEqual(record["fulfillment_method"], "AMZ")
        self.assertEqual(record["fulfillment_method_raw"], "AMZ")

    def test_direct_bsr_dom_text_has_priority_over_whole_card_fallback(self) -> None:
        card = {
            "asin": "B000000001",
            "text": "#999 in Wrong Main #888 in Wrong Child",
            "bsr_text": "#48,598 in Kitchen & Dining\n#130 in Fruit Bowls",
        }
        runtime = SimpleNamespace(
            start_url="https://www.amazon.com/gp/new-releases/home-garden/1063238/",
            field_selectors={},
        )
        node = {"url": runtime.start_url, "name": "Kitchen", "path": ["Kitchen"]}
        with (
            patch.object(category, "extract_product_cards", return_value=[card]),
            patch.object(category, "extract_table_rows", return_value=[]),
        ):
            record = category.merge_product_data(object(), runtime, node, 1, "ok")[0]
        self.assertEqual(
            record["subcategory_bsr_ranks"],
            [{"rank": 130, "category_name": "Fruit Bowls"}],
        )

    def test_product_card_extractor_requests_direct_bsr_dom_rows(self) -> None:
        class ScriptDriver:
            def __init__(self) -> None:
                self.script = ""

            def execute_script(self, script, *_args):
                self.script = script
                return []

        driver = ScriptDriver()
        category.extract_product_cards(driver)
        self.assertIn(".rank-number-box .bsr-list-item", driver.script)
        self.assertIn("bsr_text", driver.script)

    def test_readiness_signature_changes_when_fulfillment_value_changes(self) -> None:
        driver = SimpleNamespace(current_url="https://www.amazon.com/s?k=test")
        runtime = SimpleNamespace(
            sellersprite_min_fields_per_record=1,
            sellersprite_min_enriched_records=1,
        )
        rows = [
            {
                "asin": "B000000001",
                "headers": ["配送方式"],
                "cells": ["FBA卖家:1"],
                "text": "ASIN: B000000001 配送:FBA卖家:1",
            }
        ]
        with (
            patch.object(category, "extract_product_cards", return_value=[]),
            patch.object(category, "extract_table_rows", side_effect=lambda _driver: rows),
            patch.object(category, "plugin_node_count", return_value=1),
            patch.object(category, "sellersprite_login_required", return_value=False),
            patch.object(category, "detect_block", return_value=None),
        ):
            first = category.inspect_sellersprite_readiness(driver, runtime)
            rows[0]["cells"] = ["FBM卖家:1"]
            rows[0]["text"] = "ASIN: B000000001 配送:FBM卖家:1"
            second = category.inspect_sellersprite_readiness(driver, runtime)
        self.assertNotEqual(first["signature"], second["signature"])
        self.assertIn('"B000000001":"FBA"', first["signature"])
        self.assertIn('"B000000001":"FBM"', second["signature"])

    def test_readiness_uses_explicit_fulfillment_selector_semantics(self) -> None:
        driver = SimpleNamespace(current_url="https://www.amazon.com/s?k=test")
        runtime = SimpleNamespace(
            sellersprite_min_fields_per_record=1,
            sellersprite_min_enriched_records=1,
            field_selectors={"fulfillment_method": [".fulfillment"]},
        )
        cards = [
            {
                "asin": "B000000001",
                "text": "ASIN:B000000001 配送:SFPPlus",
            }
        ]
        with (
            patch.object(category, "extract_product_cards", return_value=cards),
            patch.object(category, "extract_table_rows", return_value=[]),
            patch.object(
                category,
                "extract_by_selectors",
                return_value={"fulfillment_method": "AMZ卖家:1"},
            ),
            patch.object(category, "plugin_node_count", return_value=1),
            patch.object(category, "sellersprite_login_required", return_value=False),
            patch.object(category, "detect_block", return_value=None),
        ):
            report = category.inspect_sellersprite_readiness(driver, runtime)
        self.assertIn('"B000000001":"AMZ"', report["signature"])
        self.assertEqual(report["enriched_records"], 1)

    def test_readiness_prefers_direct_bsr_dom_text(self) -> None:
        driver = SimpleNamespace(current_url="https://www.amazon.com/s?k=test")
        runtime = SimpleNamespace(
            sellersprite_min_fields_per_record=1,
            sellersprite_min_enriched_records=1,
        )
        cards = [
            {
                "asin": "B000000001",
                "text": "#999 in Wrong Main #888 in Wrong Child",
                "bsr_text": "#48,598 in Kitchen & Dining\n#130 in Fruit Bowls",
            }
        ]
        with (
            patch.object(category, "extract_product_cards", return_value=cards),
            patch.object(category, "extract_table_rows", return_value=[]),
            patch.object(category, "plugin_node_count", return_value=1),
            patch.object(category, "sellersprite_login_required", return_value=False),
            patch.object(category, "detect_block", return_value=None),
        ):
            report = category.inspect_sellersprite_readiness(driver, runtime)
        self.assertIn("Fruit Bowls", report["signature"])
        self.assertNotIn("Wrong Child", report["signature"])


class ConfigAndPersistenceTests(unittest.TestCase):
    def base_config(self) -> dict:
        return {
            "start_url": "https://www.amazon.com/gp/new-releases/home-garden/1063238/",
            "browser_backend": "cdp",
            "browser_mode": "reuse",
            "browser_tab_concurrency": 1,
            "delivery_location_enabled": False,
            "sellersprite_required": True,
        }

    def test_safety_policy_requires_one_browser_worker(self) -> None:
        runtime = category.build_runtime_config(
            self.base_config(),
            SKILL_ROOT / "assets" / "config" / "category_rank_crawler.json",
            False,
        )
        self.assertEqual(runtime.browser_tab_concurrency, 1)
        for invalid in (0, 2, 4):
            with self.assertRaises(category.UserFacingError):
                category.build_runtime_config(
                    dict(self.base_config(), browser_tab_concurrency=invalid),
                    SKILL_ROOT / "unused.json",
                    False,
                )
        with self.assertRaises(category.UserFacingError):
            category.build_runtime_config(
                dict(self.base_config(), browser_backend="selenium"),
                SKILL_ROOT / "unused.json",
                False,
            )

    def test_active_filters_require_sellersprite(self) -> None:
        raw = self.base_config()
        raw["sellersprite_required"] = False
        raw["product_filters"] = {"require_subcategory_rank": True}
        with self.assertRaises(category.UserFacingError):
            category.build_runtime_config(raw, SKILL_ROOT / "unused.json", False)

    def test_crawl_plan_fingerprint_excludes_concurrency_but_tracks_inputs(self) -> None:
        base = self.base_config()
        first = category.build_runtime_config(base, SKILL_ROOT / "unused.json", False)
        self.assertEqual(first.browser_tab_concurrency, 1)
        changed_url = category.build_runtime_config(
            dict(base, start_url="https://www.amazon.com/gp/new-releases/kitchen/1234567/"),
            SKILL_ROOT / "unused.json",
            False,
        )
        changed_depth = category.build_runtime_config(
            dict(base, max_depth=2),
            SKILL_ROOT / "unused.json",
            False,
        )
        changed_root = category.build_runtime_config(
            dict(base, include_root=True),
            SKILL_ROOT / "unused.json",
            False,
        )
        changed_selectors = category.build_runtime_config(
            dict(base, field_selectors={"subcategory_bsr_ranks": [".custom-bsr"]}),
            SKILL_ROOT / "unused.json",
            False,
        )
        self.assertNotEqual(first.crawl_plan_fingerprint, changed_url.crawl_plan_fingerprint)
        # Round 1: caps are checked separately (tightening allowed mid-job).
        self.assertEqual(first.crawl_plan_fingerprint, changed_depth.crawl_plan_fingerprint)
        self.assertNotEqual(first.crawl_plan_fingerprint, changed_root.crawl_plan_fingerprint)
        self.assertNotEqual(first.crawl_plan_fingerprint, changed_selectors.crawl_plan_fingerprint)

    def test_resume_rejects_changed_crawl_plan_after_progress(self) -> None:
        state = {"completed_pages": ["page-1"], "crawl_plan_fingerprint": "old"}
        with self.assertRaises(category.UserFacingError):
            category.ensure_resume_crawl_plan_fingerprint(
                state,
                SimpleNamespace(crawl_plan_fingerprint="new"),
            )

    def test_pending_only_state_rebuilds_queue_when_crawl_plan_changes(self) -> None:
        def make_runtime(start_url: str, resume: bool) -> SimpleNamespace:
            return SimpleNamespace(
                start_url=start_url,
                job_id="plan-reset-test",
                resume=resume,
                delivery_location_fingerprint="delivery-v1",
                record_contract_fingerprint="contract-v1",
                crawl_plan_fingerprint=category.crawl_plan_fingerprint(
                    start_url, False, None, None, {}
                ),
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            first_url = "https://www.amazon.com/gp/bestsellers/home/1000"
            second_url = "https://www.amazon.com/gp/bestsellers/kitchen/2000"
            first = category.StateStore(
                state_path, make_runtime(first_url, False)
            )
            first.load_or_create()

            resumed = category.StateStore(
                state_path, make_runtime(second_url, True)
            )
            resumed.load_or_create()
            self.assertEqual(resumed.data["start_url"], second_url)
            self.assertEqual(resumed.data["queue"][0]["url"], second_url)
            self.assertEqual(resumed.data["pending"][0]["url"], second_url)

    def test_dump_json_replaces_same_directory_temp_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "state.json"
            target.write_text('{"old": true}\n', encoding="utf-8")
            calls = []
            real_replace = category.os.replace

            def replace_spy(source: object, destination: object) -> None:
                calls.append((Path(source), Path(destination)))
                real_replace(source, destination)

            with patch.object(category.os, "replace", side_effect=replace_spy):
                category.dump_json(target, {"new": True})

            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"new": True})
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][0].parent, target.parent)
            self.assertEqual(calls[0][1], target)
            self.assertFalse(calls[0][0].exists())

    def test_job_run_lock_rejects_a_second_process_writer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = Path(temp_dir) / ".run.lock"
            first = category.JobRunLock(lock_path)
            second = category.JobRunLock(lock_path)
            first.acquire()
            try:
                with self.assertRaises(category.UserFacingError):
                    second.acquire()
            finally:
                first.release()
            second.acquire()
            second.release()


class CategoryCheckpointRecoveryTests(unittest.TestCase):
    def state_data(self, nodes: list[dict]) -> dict:
        return {
            "state_version": 2,
            "queue": nodes,
            "current": None,
            "in_flight_categories": {},
            "seen_categories": [category.category_key(node) for node in nodes],
            "done_categories": [],
            "completed_pages": [],
            "processed_categories_count": 0,
            "records_count": 0,
            "filtered_out_count": 0,
            "filter_rejection_counts": {},
            "failures_count": 0,
            "delivery_location_fingerprint": "delivery-v1",
            "record_contract_fingerprint": "contract-v1",
            "crawl_plan_fingerprint": "plan-v1",
        }

    def test_stale_inflight_category_is_recovered_for_sequential_resume(self) -> None:
        nodes = [
            {"url": "https://www.amazon.com/a", "name": "A", "path": ["A"]},
            {"url": "https://www.amazon.com/b", "name": "B", "path": ["B"]},
            {"url": "https://www.amazon.com/c", "name": "C", "path": ["C"]},
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            state = category.StateStore(
                Path(temp_dir) / "state.json",
                SimpleNamespace(),
            )
            state.data = self.state_data([nodes[2]])
            state.data["current"] = {"node": nodes[0], "page_number": 2}
            state.data["in_flight_categories"] = {
                category.category_key(nodes[1]): {"node": nodes[1]}
            }
            state.flush = lambda: None
            state.recover_stale_in_flight()
            # Sequential resume: the crashed in-flight category goes back to the
            # head of the queue and the current page is kept as is.
            self.assertEqual(state.data["queue"], [nodes[1], nodes[2]])
            self.assertEqual(state.data["current"], {"node": nodes[0], "page_number": 2})
            self.assertEqual(state.data["in_flight_categories"], {})

    def test_page_shard_recovers_crash_and_materializes_page_asin_once(self) -> None:
        runtime = SimpleNamespace(
            resume=True,
            delivery_location_fingerprint="delivery-v1",
            record_contract_fingerprint="contract-v1",
            crawl_plan_fingerprint="plan-v1",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state_path = root / "state.json"
            state = category.StateStore(state_path, runtime)
            state.data = self.state_data([])
            state.flush()
            stale_state = copy.deepcopy(state.data)
            page = category.CategoryPageBatch(
                key="node:1|page:1|url",
                page_number=1,
                page_url="https://www.amazon.com/a",
                plugin_status="ok",
                extracted_count=2,
                records=[{"asin": "B000000001"}, {"asin": "B000000001"}],
                rejection_counts={},
            )
            self.assertTrue(state.commit_page_batch(page))

            # Simulate a crash after atomic page shard creation but before state.json commit.
            category.dump_json(state_path, stale_state)
            resumed = category.StateStore(state_path, runtime)
            resumed.load_or_create()
            records_path = root / "records.jsonl"
            category.materialize_category_records(resumed, records_path)

            self.assertEqual(resumed.data["completed_pages"], [page.key])
            self.assertEqual(resumed.data["records_count"], 1)
            self.assertEqual(category.read_jsonl(records_path), [{"asin": "B000000001"}])


class ManualPromptCoordinationTests(unittest.TestCase):
    def test_final_plugin_prompt_emits_pause_and_resume_callbacks(self) -> None:
        runtime = SimpleNamespace(
            sellersprite_required=True,
        )
        driver = SimpleNamespace(current_url="https://www.amazon.com/s?k=test")
        events = []
        with (
            patch.object(
                category,
                "wait_for_sellersprite_data",
                side_effect=["plugin_absent", "ok"],
            ),
            patch.object(
                category,
                "get_sellersprite_readiness",
                return_value={"status": "plugin_absent"},
            ),
            patch.object(
                category,
                "category_page_assessment",
                return_value=category.PageHealthAssessment(
                    status=category.PageHealthStatus.HEALTHY,
                    reason="expected_content_present",
                    page_kind="search_category",
                ),
            ),
            patch.object(category, "wait_for_user_plugin_action"),
            patch.object(category, "wait_for_amazon_products"),
        ):
            status = category.wait_for_sellersprite_data_or_prompt(
                driver,
                runtime,
                on_manual_pause=lambda reason, url: events.append(("pause", reason, url)),
                on_manual_resume=lambda: events.append(("resume",)),
            )
        self.assertEqual(status, "ok")
        self.assertEqual(events[0][:2], ("pause", "sellersprite_manual_action"))
        self.assertEqual(events[-1], ("resume",))

    def test_manual_and_sellersprite_waits_honor_stop_event(self) -> None:
        stop_event = threading.Event()
        stop_event.set()
        with self.assertRaises(category.ConcurrentWorkerCancelled):
            category.wait_for_manual_continue(30, stop_event=stop_event)
        with self.assertRaises(category.ConcurrentWorkerCancelled):
            category.wait_for_sellersprite_data_or_prompt(
                SimpleNamespace(current_url="https://www.amazon.com/"),
                SimpleNamespace(sellersprite_required=True),
                stop_event=stop_event,
            )

    def test_plugin_manual_action_no_longer_uses_unbounded_input(self) -> None:
        driver = SimpleNamespace(refresh=lambda: None)
        with patch.object(category, "wait_for_manual_continue", return_value=False) as wait:
            continued = category.wait_for_user_plugin_action(
                driver,
                "login",
                manual_pause_timeout=12,
            )
        self.assertFalse(continued)
        wait.assert_called_once_with(12)


if __name__ == "__main__":
    unittest.main()
