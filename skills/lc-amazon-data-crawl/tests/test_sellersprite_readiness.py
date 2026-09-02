from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import amazon_category_rank_crawler as category
import amazon_image_competitor_crawler as image
from browser_runtime import CdpWebDriver, cdp_endpoint, expected_profile_path, profile_paths_match
from start_cdp_browser import (
    SELLERSPRITE_EXTENSION_ID,
    discover_chrome_for_testing,
    discover_sellersprite_extension,
    should_auto_start,
)


class SellerSpriteReadinessTests(unittest.TestCase):
    def classify(self, **overrides: object) -> str:
        snapshot = {
            "blocked": False,
            "plugin_nodes": 1,
            "login_required": False,
            "product_count": 10,
            "enriched_records": 1,
            "max_fields_per_record": 2,
        }
        snapshot.update(overrides)
        return category.classify_sellersprite_snapshot(snapshot, 1, 2)

    def test_state_classification(self) -> None:
        self.assertEqual(self.classify(blocked=True), "blocked")
        self.assertEqual(self.classify(plugin_nodes=0), "plugin_absent")
        self.assertEqual(self.classify(login_required=True), "login_required")
        self.assertEqual(self.classify(product_count=0), "data_loading")
        self.assertEqual(self.classify(enriched_records=0), "data_loading")
        self.assertEqual(self.classify(max_fields_per_record=1), "data_loading")
        self.assertEqual(self.classify(), "ready_candidate")

    def test_empty_plugin_table_is_not_ready(self) -> None:
        self.assertEqual(
            self.classify(
                plugin_nodes=4,
                product_count=20,
                enriched_records=0,
                max_fields_per_record=0,
            ),
            "data_loading",
        )

    def test_ready_requires_configured_stability(self) -> None:
        runtime = SimpleNamespace(
            sellersprite_required=True,
            activate_plugin=False,
            page_scroll_before_extract=False,
            plugin_timeout=10,
            sellersprite_stable_checks=3,
        )
        driver = SimpleNamespace(current_url="https://www.amazon.com/s?k=test")
        report = {
            "status": "ready_candidate",
            "checked_at": "2026-07-29T00:00:00Z",
            "signature": "stable",
        }
        with (
            patch.object(
                category,
                "inspect_sellersprite_readiness",
                side_effect=lambda *_: dict(report),
            ) as inspect,
            patch.object(category.time, "sleep"),
        ):
            self.assertEqual(category.wait_for_sellersprite_data(driver, runtime), "ok")
        self.assertEqual(inspect.call_count, 3)
        self.assertEqual(category.get_sellersprite_readiness(driver)["status"], "ready")

    def test_state_persistence_drops_internal_signature(self) -> None:
        safe = category.safe_sellersprite_readiness(
            {
                "status": "ready",
                "signature": "internal",
                "plugin_nodes": 2,
                "enriched_records": 3,
            }
        )
        self.assertNotIn("signature", safe)
        self.assertEqual(safe["status"], "ready")

    def test_late_amazon_sign_in_keeps_real_block_reason_and_stops(self) -> None:
        driver = SimpleNamespace(current_url="https://www.amazon.com/ap/signin")
        runtime = SimpleNamespace(
            sellersprite_required=True,
            manual_pause_timeout=900,
        )
        pauses: list[tuple[str, str]] = []
        with (
            patch.object(category, "wait_for_sellersprite_data", return_value="blocked"),
            patch.object(
                category,
                "get_sellersprite_readiness",
                return_value={"blocked_reason": "amazon_sign_in"},
            ),
            patch.object(category, "wait_for_manual_continue") as wait,
            self.assertRaisesRegex(
                category.VerificationUnconfirmedError,
                "amazon_sign_in_terminal",
            ),
        ):
            category.wait_for_sellersprite_data_or_prompt(
                driver,
                runtime,
                on_manual_pause=lambda reason, url: pauses.append((reason, url)),
            )
        wait.assert_not_called()
        self.assertEqual(
            pauses,
            [("amazon_sign_in", "https://www.amazon.com/ap/signin")],
        )


class BrowserBackendTests(unittest.TestCase):
    def test_cdp_endpoint_normalization(self) -> None:
        self.assertEqual(cdp_endpoint("127.0.0.1:9222"), "http://127.0.0.1:9222")
        self.assertEqual(cdp_endpoint("http://localhost:9222/"), "http://localhost:9222")

    def test_expected_profile_path(self) -> None:
        base = SKILL_ROOT / "chrome_profiles" / "lc-amazon-data-crawl"
        self.assertEqual(expected_profile_path(base, "Default"), (base / "Default").resolve())
        self.assertTrue(profile_paths_match(str(base / "Default"), base, "Default"))
        self.assertFalse(profile_paths_match(str(base / "Profile 2"), base, "Default"))

    def test_cdp_backend_does_not_call_webdriver_chrome(self) -> None:
        runtime = SimpleNamespace(
            browser_backend="cdp",
            browser_mode="launch",
            page_timeout=90,
            debugger_address="127.0.0.1:9222",
            chrome_user_data_dir=SKILL_ROOT / "chrome_profiles" / "test",
            chrome_profile_directory="Default",
        )
        sentinel = object()
        with (
            patch.object(category, "launch_debug_chrome", return_value=False),
            patch.object(category, "CdpWebDriver", return_value=sentinel) as cdp_driver,
            patch.object(category.webdriver, "Chrome") as chrome_driver,
        ):
            self.assertIs(category.start_driver(runtime), sentinel)
        cdp_driver.assert_called_once()
        chrome_driver.assert_not_called()

    def test_owned_cdp_browser_uses_browser_close_command(self) -> None:
        driver = CdpWebDriver.__new__(CdpWebDriver)
        driver._closed = False
        driver._owns_browser = True
        session = MagicMock()
        driver._browser_cdp_session = session
        driver._playwright = MagicMock()
        driver._browser = MagicMock()
        driver._context = MagicMock()
        driver._page = MagicMock()
        driver._owned_process = None
        driver.quit()
        session.send.assert_called_once_with("Browser.close")

    def test_sellersprite_auto_discovery_prefers_newest_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for version in ("5.0.3_0", "5.0.4_0"):
                extension_dir = (
                    root
                    / "Default"
                    / "Extensions"
                    / SELLERSPRITE_EXTENSION_ID
                    / version
                )
                extension_dir.mkdir(parents=True)
                (extension_dir / "manifest.json").write_text(
                    json.dumps({"name": "__MSG_ext_name__", "version": version[:-2]}),
                    encoding="utf-8",
                )
            discovered = discover_sellersprite_extension([root])
            self.assertEqual(
                discovered,
                (
                    root
                    / "Default"
                    / "Extensions"
                    / SELLERSPRITE_EXTENSION_ID
                    / "5.0.4_0"
                ).resolve(),
            )

    def test_chrome_for_testing_auto_discovery_prefers_newest_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            candidates = []
            for version in ("149.0.7827.55", "151.0.7922.47"):
                binary = (
                    root
                    / version
                    / "Google Chrome for Testing.app"
                    / "Contents"
                    / "MacOS"
                    / "Google Chrome for Testing"
                )
                binary.parent.mkdir(parents=True)
                binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                binary.chmod(0o755)
                candidates.append(binary)
            self.assertEqual(
                discover_chrome_for_testing(candidates),
                candidates[-1].resolve(),
            )

    def test_auto_start_only_applies_to_cdp_reuse(self) -> None:
        self.assertTrue(
            should_auto_start(
                {"browser_backend": "cdp", "browser_mode": "reuse"}
            )
        )
        self.assertFalse(
            should_auto_start(
                {"browser_backend": "cdp", "browser_mode": "launch"}
            )
        )
        self.assertFalse(
            should_auto_start(
                {"browser_backend": "selenium", "browser_mode": "reuse"}
            )
        )


class ConfigCompatibilityTests(unittest.TestCase):
    def test_templates_default_to_cdp(self) -> None:
        template_names = (
            "amazon_front_bsr_category.json",
            "amazon_front_keyword_search.json",
            "amazon_front_storefront.json",
            "amazon_image_competitors.json",
            "category_rank_crawler.json",
        )
        for template_name in template_names:
            config_path = SKILL_ROOT / "assets" / "config" / template_name
            raw = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(raw["browser_backend"], "cdp", config_path.name)
            self.assertEqual(raw["browser_mode"], "reuse", config_path.name)
            self.assertEqual(raw["chrome_binary"], "auto", config_path.name)
            self.assertEqual(
                raw["chrome_user_data_dir"],
                "chrome_profiles/lc-amazon-data-crawl-cft",
                config_path.name,
            )
            self.assertEqual(raw["extension_path"], "auto", config_path.name)
            self.assertFalse(raw["activate_plugin"], config_path.name)

    def test_setup_runner_uses_cdp_runtime_and_auto_starts_reuse_chrome(self) -> None:
        setup_text = (SKILL_ROOT / "scripts" / "setup_runner.sh").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("-m playwright install chromium", setup_text)
        self.assertIn("from playwright.sync_api import sync_playwright", setup_text)
        self.assertIn("auto_start_reuse_browser", setup_text)

    def test_count_only_image_mode_does_not_require_sellersprite(self) -> None:
        config_path = SKILL_ROOT / "assets" / "config" / "amazon_image_competitors.json"
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        raw["products_file"] = str(
            SKILL_ROOT / "assets" / "inputs" / "image_competitors.example.csv"
        )
        runtime = image.build_image_runtime_config(raw, no_resume=False)
        self.assertTrue(runtime.is_count_only)
        self.assertFalse(runtime.sellersprite_required)

    def test_image_detail_reuses_explicit_fulfillment_prefix_parser(self) -> None:
        asin = "B000000001"
        runtime = SimpleNamespace(
            is_count_only=False,
            max_candidates_per_source=10,
            field_selectors={},
        )
        card = {
            "asin": asin,
            "title": "fixture",
            "product_url": f"https://www.amazon.com/dp/{asin}",
            "candidate_image_url": "https://example.invalid/image.jpg",
            "rank": 1,
            "text": f"ASIN:{asin} FBA费用:$3.81",
        }
        table_row = {
            "asin": asin,
            "headers": ["ASIN", "配送方式"],
            "cells": [asin, "FBMPlus"],
            "text": f"ASIN:{asin} 配送:FBMPlus",
        }
        with (
            patch.object(image, "collect_lens_candidate_cards", return_value=[card]),
            patch.object(image, "extract_table_rows", return_value=[table_row]),
            patch.object(image, "extract_by_selectors", return_value={}),
        ):
            records = image.merge_lens_product_data(
                SimpleNamespace(),
                runtime,
                {"source_id": "fixture", "source_asin": "B000000099"},
                "ok",
            )
        self.assertEqual(records[0]["fulfillment_method"], "FBM")

    def test_image_count_only_still_skips_fulfillment_enrichment(self) -> None:
        asin = "B000000001"
        runtime = SimpleNamespace(
            is_count_only=True,
            max_candidates_per_source=10,
            field_selectors={},
        )
        card = {
            "asin": asin,
            "title": "fixture",
            "product_url": f"https://www.amazon.com/dp/{asin}",
            "candidate_image_url": "https://example.invalid/image.jpg",
            "rank": 1,
            "text": f"ASIN:{asin} 配送:FBMPlus",
        }
        with (
            patch.object(image, "collect_lens_candidate_cards", return_value=[card]),
            patch.object(image, "extract_table_rows") as extract_table_rows,
        ):
            records = image.merge_lens_product_data(
                SimpleNamespace(),
                runtime,
                {"source_id": "fixture", "source_asin": "B000000099"},
                "not_required",
            )
        extract_table_rows.assert_not_called()
        self.assertEqual(records[0]["fulfillment_method"], "")


if __name__ == "__main__":
    unittest.main()
