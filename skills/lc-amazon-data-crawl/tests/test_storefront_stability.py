from __future__ import annotations

import hashlib
import os
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import amazon_category_rank_crawler as shared
import amazon_front_crawler as front
import run_outcome


class StabilityTests(unittest.TestCase):
    def test_provider_na_zero_rating_and_delivery_boundaries(self):
        for token in ("N/A", "NA", "--", "—", "–", "无"):
            self.assertEqual(shared.sellersprite_field_status("fba_fee", token), "explicit_unavailable")
        for token in (0, "0.00", "0.000", "0%"):
            self.assertEqual(shared.sellersprite_field_status("sales_30_days_child", token), "zero_unconfirmed")
        self.assertEqual(shared.parse_field_from_text("review_count", "评分(评分数): N/A (N/A)"), "N/A")
        self.assertEqual(shared.parse_field_from_text("gross_margin", "毛利率: -12%"), "-12%")
        polluted = "FREE delivery Oct 15 - 26 Or fastest delivery Oct 8 - 13 Add to cart ASIN:B000000001 加入产品库"
        self.assertEqual(shared.parse_field_from_text("delivery_duration", polluted), "")
        self.assertEqual(shared.sellersprite_field_status("delivery_duration", polluted), "invalid")
        self.assertEqual(shared.parse_field_from_text("delivery_duration", "配送时长: 11-18天 上架时间: 2026-10-01"), "11-18天")
        self.assertEqual(shared.parse_field_from_text("launch_date", "上架时间: N/A 自然搜索词: 0"), "N/A")
        self.assertEqual(shared.parse_field_from_text("seller_country", "Country House) Full coverage on 14CT cotton Aida"), "")
        self.assertEqual(shared.parse_field_from_text("seller_country", "Country: United States Brand: Generic"), "United States")

    def test_brand_without_seller_does_not_capture_plugin_controls(self):
        for text, expected in (
            ("ASIN:B000000001\n品牌:\nGeneric\n加入产品库\n近30天销量(父体):N/A", "Generic"),
            ("品牌: WGYBL 加入产品库 #1,234 in Tools 近30天销量(父体):23", "WGYBL"),
            ("品牌: Acme Home 卖家: Bob 配送: FBA", "Acme Home"),
            ("Brand: Acme Home\nSeller: Bob", "Acme Home"),
            ("Country House product without a brand label", ""),
        ):
            self.assertEqual(shared.parse_field_from_text("brand_name", text), expected)
        self.assertEqual(shared.sellersprite_field_status("brand_name", "WGYBL 加入产品库"), "invalid")

    def test_amazon_delivery_fallback_excludes_stock_message(self):
        driver = SimpleNamespace(current_url="https://www.amazon.com/s")
        runtime = SimpleNamespace(page_extraction_engine="browser", field_selectors={}, sellersprite_required=True)
        card = {"asin": "B000000001", "text": "Product", "delivery_text":
                "$5.99 delivery Oct 14 - 22 Only 20 left in stock - order soon. Add to cart"}
        with (
            patch.object(front, "extract_front_product_cards", return_value=[card]),
            patch.object(front, "extract_table_rows", return_value=[]),
            patch.object(front, "extract_by_selectors", return_value={}),
        ):
            rows = front.merge_front_product_data(driver, runtime, {}, "ok")
        self.assertEqual(rows[0]["delivery_duration"], "Oct 14 - 22")

    def test_all_and_nonadjacent_content_loop(self):
        self.assertIsNone(front.parse_store_page_limit("all"))
        self.assertEqual(front.parse_store_page_limit(20), 20)
        for invalid in (True, 0, 21, "", "unlimited"):
            with self.assertRaises(shared.UserFacingError):
                front.parse_store_page_limit(invalid)
        current = {"source_type": "storefront", "page_number": 20, "page_url": "https://www.amazon.com/s?me=TEST&page=20"}
        driver = SimpleNamespace(current_url=current["page_url"])
        rows = [{"asin": "B000000001"}]
        with patch.object(front, "find_next_page_url", return_value="https://www.amazon.com/s?me=TEST&page=21"):
            task, reason = front.build_next_front_task(driver, SimpleNamespace(store_page_limit=None), current, rows)
        self.assertEqual(task["page_number"], 21)
        self.assertFalse(reason)
        historical = hashlib.sha256("B000000002".encode()).hexdigest()
        task["seen_asin_sets"].append(historical)
        self.assertTrue(front.should_stop_on_repeated_store_page(task, [{"asin": "B000000002"}]))

    def test_missing_historical_status_is_not_complete(self):
        self.assertEqual(shared.quality_counts([])["status"], "not_evaluated")
        report = shared.quality_counts([{"asin": "B000000001", "delivery_duration": "Add to cart ASIN:B000000001"}])
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["by_field"]["delivery_duration"]["invalid"], 1)
        self.assertEqual(report["by_field"]["subcategory_bsr_ranks"]["missing"], 1)

    def test_render_evidence_is_saved_without_extra_private_fields(self):
        report = shared.safe_sellersprite_readiness({
            'status': 'timeout', 'token': 'private',
            'page_render': {'document_hidden': True, 'focused': False,
                            'frame_supported': True, 'frame_callbacks': 0,
                            'frame_pending_ms': 40000, 'last_frame_age_ms': None,
                            'visibility_state': 'hidden', 'reactivation_hidden': False, 'token': 'private'},
        })
        self.assertNotIn('token', report)
        self.assertNotIn('token', report['page_render'])
        self.assertEqual(report['page_render']['frame_callbacks'], 0)
        self.assertEqual(report['page_render']['frame_pending_ms'], 40000)
        self.assertIs(report['page_render']['reactivation_hidden'], False)

    def test_render_evidence_is_written_before_screenshot(self):
        with tempfile.TemporaryDirectory() as temp:
            worker = object.__new__(front.FrontWorker)
            worker.runtime = SimpleNamespace(save_debug_snapshots=True)
            worker.driver = object()
            worker.debug_dir = Path(temp)
            worker.worker_id = 'tab-1'
            worker._readiness = {'status': 'timeout', 'page_render': {'frame_callbacks': 0}}
            def check_evidence(*_):
                evidence = json.loads((Path(temp) / 'render_evidence.jsonl').read_text().strip())
                self.assertEqual(evidence['readiness']['page_render']['frame_callbacks'], 0)
            with patch.object(front, 'save_debug_snapshot', side_effect=check_evidence):
                worker._save_debug({'source_type': 'storefront', 'page_number': 2}, 'plugin_data_timeout')

    def test_final_summary_cannot_deliver_empty_core_or_truncated_all(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = {"mode": "storefront", "scope_requested": "all", "requested_source_ids": ["store"],
                     "completed_source_reasons": {"store": "store_page_limit"}, "pending": [], "in_flight": {}}
            (root / "state.json").write_text(json.dumps(state))
            report = {"schema_version": 2, "status": "failed", "export_succeeded": True}
            (root / "quality_report.json").write_text(json.dumps(report))
            run_outcome.finalize_run(root, run_outcome.completed_outcome(0))
            summary = json.loads((root / "run_summary.json").read_text())
            self.assertFalse(summary["delivery_ready"])
            self.assertFalse(summary["scope_completion"]["complete"])
            state["completed_source_reasons"]["store"] = "no_next_page"
            (root / "state.json").write_text(json.dumps(state))
            report["status"] = "passed"
            (root / "quality_report.json").write_text(json.dumps(report))
            run_outcome.finalize_run(root, run_outcome.completed_outcome(0))
            self.assertTrue(json.loads((root / "run_summary.json").read_text())["delivery_ready"])
            run_outcome.finalize_run(root, run_outcome.Outcome(21, "risk_pause", "risk", "wait"))
            summary = json.loads((root / "run_summary.json").read_text())
            self.assertEqual(summary["next_action"], "wait")
            self.assertFalse(summary["delivery_ready"])


@unittest.skipUnless(os.environ.get("LC_RUN_BROWSER_TESTS") == "1", "browser tests require LC_RUN_BROWSER_TESTS=1")
class RealVisibleDomTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        candidates = [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                      Path("/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing")]
        chrome = next((p for p in candidates if p.is_file()), None)
        if chrome is None:
            raise unittest.SkipTest("system Chrome unavailable")
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(executable_path=str(chrome), headless=True)
        cls.page = cls.browser.new_page()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def driver(self, html):
        self.page.set_content(html)
        page = self.page
        class Driver:
            current_url = "https://www.amazon.com/s?me=TEST"
            title = "Amazon"
            def execute_script(self, script, *args):
                return page.evaluate("([script,args]) => (new Function(script)).apply(null,args)", [script, list(args)])
            def find_element(self, *args):
                return SimpleNamespace(text=page.locator("body").inner_text())
        return Driver()

    def test_hidden_real_challenge_and_global_body_class(self):
        html = '<body class="seller-sprite-invincible"><nav class="nav-sprite">请登录 验证码</nav><div data-asin="B000000001">product</div><div style="display:none"><div class="robot-card-container"><div class="robot-dialog">机器人检测<input><button>我不是机器人</button></div></div></div><div name="seller-sprite-extension-quick-view-B000000001">品牌: generic</div></body>'
        driver = self.driver(html)
        self.assertIsNone(shared.detect_block(driver))
        self.assertFalse(shared.sellersprite_login_required(driver))
        self.assertNotIn("机器人", shared.sellersprite_visible_text(driver))
        driver = self.driver(html.replace('style="display:none"', 'style="display:block"'))
        self.assertEqual(shared.detect_block(driver), "sellersprite_verification")
        self.assertTrue(driver._lc_block_evidence["nodes"][0]["visible"])
        self.page.locator(".robot-card-container").evaluate("el => el.style.visibility='hidden'")
        self.assertIsNone(shared.detect_block(driver))

    def test_buyer_suggestion_and_function_menu(self):
        driver = self.driver('<div data-asin="B000000001">product</div><div id="seller-sprite-root">机器人检测<br>为避免影响查看BSR，请先登录亚马逊买家账号！</div>')
        self.assertIsNone(shared.detect_block(driver))
        self.assertFalse(shared.sellersprite_login_required(driver))
        driver = self.driver('<div data-asin="B000000001">product</div><div id="seller-sprite-root">登录卖家精灵</div>')
        self.assertTrue(shared.sellersprite_login_required(driver))
        driver = self.driver('<div data-asin="B000000001">product</div><div id="seller-sprite-root"><div role="dialog">请输入验证码<input></div></div>')
        self.assertEqual(shared.detect_block(driver), "sellersprite_verification")

    def test_store_list_excludes_cart_and_selects_visible_duplicate_card(self):
        labels = '<div>近30天销量(父体): N/A</div><div>近30天销量(子体): N/A</div><div>FBA费用: N/A</div><div>毛利率: N/A</div>'
        html = '<div class="s-main-slot"><div class="s-result-item" data-asin="B000000001"><h2>Store product</h2></div></div><aside data-asin="B000000002">Cart product</aside>'
        html += '<div style="display:none" name="seller-sprite-extension-quick-view-B000000001">hidden</div>'
        html += '<div class="quick-view-ext" name="seller-sprite-extension-quick-view-B000000001">' + labels + '</div>'
        driver = self.driver(html)
        cards = front.extract_front_product_cards(driver, True)
        self.assertEqual([row["asin"] for row in cards], ["B000000001"])
        snapshot = front.inspect_storefront_plugin_page(driver, SimpleNamespace(include_sponsored=False, page_scroll_step_ratio=.85), scroll=False)
        self.assertEqual(snapshot["complete_count"], 1)

        self.assertEqual(snapshot["pending"], {})
        fields = ''.join('<span class="word-title">' + label + ':</span><span>N/A</span>' for label in front.STOREFRONT_REQUIRED_PLUGIN_LABELS)
        html = '<div class="s-main-slot"><div class="s-result-item" data-asin="B000000001"><div class="quick-view-ext" name="seller-sprite-extension-quick-view-B000000001" style="display:flex">' + fields + '</div></div></div>'
        snapshot = front.inspect_storefront_plugin_page(self.driver(html), SimpleNamespace(include_sponsored=False, page_scroll_step_ratio=.85), scroll=False)
        self.assertEqual(snapshot["complete_count"], 1)

    def test_recycled_cards_keep_evidence_only_within_same_page(self):
        fields = ''.join('<span class="word-title">' + label + ':</span><span>N/A</span>' for label in front.STOREFRONT_REQUIRED_PLUGIN_LABELS)
        fields += '<span class="flag-icon flag-icon-cn" style="display:inline-block;width:24px;height:16px"></span>'
        driver = self.driver('<div class="s-main-slot"><div class="s-result-item" data-asin="B000000001"><div class="quick-view-ext" name="seller-sprite-extension-quick-view-B000000001">' + fields + '</div></div></div>')
        runtime = SimpleNamespace(include_sponsored=False, page_scroll_step_ratio=.85, save_page_evidence=True)
        first = front.inspect_storefront_plugin_page(driver, runtime, scroll=False)
        self.assertEqual(first["complete_count"], 1)
        self.assertEqual(driver._lc_storefront_cards['cards']['B000000001']['seller_country_flag_code'].lower(), 'cn')
        self.assertIn('flag-icon-cn', driver._lc_storefront_cards['htmls']['B000000001'])
        self.page.locator('.quick-view-ext').evaluate('el => el.remove()')
        recycled = front.inspect_storefront_plugin_page(driver, runtime, scroll=False)
        self.assertEqual(recycled["complete_count"], 1)
        self.assertEqual(recycled["signature"], first["signature"])
        self.assertIn('N/A', recycled['texts']['B000000001'])
        runtime.field_selectors = {}
        runtime.sellersprite_required = True
        with patch.object(front, 'extract_table_rows', return_value=[]), patch.object(front, 'extract_by_selectors', return_value={}):
            row = front.merge_front_product_data(driver, runtime, {}, 'ok', plugin_texts=recycled['texts'], plugin_values=recycled['values'])[0]
        self.assertEqual(row['_source_country_flag_code'].lower(), 'cn')
        self.assertEqual(row['seller_country'], shared.country_from_flag_code_or_text('cn'))
        self.assertIn('flag-icon-cn', row['_source_plugin_html'])
        driver.page_epoch = 2
        reset = front.inspect_storefront_plugin_page(driver, runtime, scroll=False)
        self.assertEqual(reset["complete_count"], 0)
        self.assertEqual(reset["pending"], {'B000000001': 'plugin_box_missing'})

    def test_lazy_plugin_below_tall_amazon_card_is_brought_into_view(self):
        fields = ''.join('<div>' + label + ': N/A</div>' for label in front.STOREFRONT_REQUIRED_PLUGIN_LABELS)
        driver = self.driver('<div class="s-main-slot"><div class="s-result-item" data-asin="B000000001"><div style="height:1200px"><h2>Tall product</h2></div><div id="lazy" class="quick-view-ext" name="seller-sprite-extension-quick-view-B000000001" style="height:180px"></div></div></div><footer style="height:1000px"></footer>')
        self.page.evaluate('fields => { const el=document.querySelector("#lazy"); const observer=new IntersectionObserver(entries => { if(entries.some(x=>x.isIntersecting)) { el.innerHTML=fields; observer.disconnect(); } }); observer.observe(el); }', fields)
        runtime = SimpleNamespace(include_sponsored=False, page_scroll_step_ratio=.85, storefront_plugin_stable_seconds=.05)
        with patch.object(front, 'inspect_sellersprite_block', return_value={'status': 'ready_candidate'}):
            result = front.wait_for_storefront_plugin_page(driver, runtime, time.monotonic() + 5)
        self.assertEqual(result, 'ok')
        self.assertEqual(front.get_sellersprite_readiness(driver)['enriched_records'], 1)

    def test_render_evidence_does_not_change_readiness(self):
        fields = ''.join('<div>' + label + ': N/A</div>' for label in front.STOREFRONT_REQUIRED_PLUGIN_LABELS)
        driver = self.driver('<div class="s-main-slot"><div class="s-result-item" data-asin="B000000001"><div class="quick-view-ext" name="seller-sprite-extension-quick-view-B000000001">' + fields + '</div></div></div>')
        runtime = SimpleNamespace(include_sponsored=False, page_scroll_step_ratio=.85)
        driver.page_epoch = 1
        first = front.inspect_storefront_plugin_page(driver, runtime, scroll=False)
        self.page.wait_for_timeout(100)
        active = front.inspect_storefront_plugin_page(driver, runtime, scroll=False)
        self.assertGreater(active['page_render']['frame_callbacks'], 0)
        self.assertEqual(first['signature'], active['signature'])
        original = 'window.__lcOriginalRaf = window.requestAnimationFrame; window.requestAnimationFrame = () => 0;'
        self.page.evaluate(original)
        try:
            driver.page_epoch = 2
            front.inspect_storefront_plugin_page(driver, runtime, scroll=False)
            self.page.wait_for_timeout(100)
            stalled = front.inspect_storefront_plugin_page(driver, runtime, scroll=False)
            self.assertEqual(stalled['page_render']['frame_callbacks'], 0)
            self.assertGreaterEqual(stalled['page_render']['frame_pending_ms'], 50)
            self.assertEqual(stalled['complete_count'], 1)
            self.assertEqual(stalled['signature'], first['signature'])
        finally:
            self.page.evaluate('window.requestAnimationFrame = window.__lcOriginalRaf; delete window.__lcOriginalRaf; delete window.__lcStorefrontRenderProbe;')


    def test_visible_required_field_disappearing_invalidates_old_cache(self):
        fields = ''.join('<div>' + label + ': N/A</div>' for label in front.STOREFRONT_REQUIRED_PLUGIN_LABELS)
        driver = self.driver('<div class="s-main-slot"><div class="s-result-item" data-asin="B000000001"><div class="quick-view-ext" name="seller-sprite-extension-quick-view-B000000001">' + fields + '</div></div></div>')
        runtime = SimpleNamespace(include_sponsored=False, page_scroll_step_ratio=.85)
        self.assertEqual(front.inspect_storefront_plugin_page(driver, runtime, scroll=False)['complete_count'], 1)
        self.page.locator('.quick-view-ext div').last.evaluate('el => el.remove()')
        result = front.inspect_storefront_plugin_page(driver, runtime, scroll=False)
        self.assertEqual(result['complete_count'], 0)
        self.assertIn('field_missing', result['pending']['B000000001'])

    def test_offscreen_field_recycling_retains_confirmed_cache(self):
        fields = ''.join('<div>' + label + ': N/A</div>' for label in front.STOREFRONT_REQUIRED_PLUGIN_LABELS)
        driver = self.driver('<div class="s-main-slot"><div class="s-result-item" data-asin="B000000001"><div class="quick-view-ext" name="seller-sprite-extension-quick-view-B000000001">' + fields + '</div></div></div>')
        runtime = SimpleNamespace(include_sponsored=False, page_scroll_step_ratio=.85)
        self.assertEqual(front.inspect_storefront_plugin_page(driver, runtime, scroll=False)['complete_count'], 1)
        self.page.locator('.quick-view-ext').evaluate('el => { el.style.marginTop="1800px"; el.innerHTML=""; }')
        self.assertEqual(front.inspect_storefront_plugin_page(driver, runtime, scroll=False)['complete_count'], 1)
        driver.page_epoch = 2
        self.assertEqual(front.inspect_storefront_plugin_page(driver, runtime, scroll=False)['complete_count'], 0)

    def test_known_more_button_loading_label_does_not_end_store_or_keyword(self):
        import result_pagination as pagination
        driver=self.driver('<div id="search"><div class="s-main-slot"><div class="s-result-item" data-asin="B000000001"></div></div><button id="more">Show more results</button></div>')
        self.assertIsNotNone(pagination.find_load_more_control(driver))
        self.page.locator('#more').evaluate('el => { el.textContent="Loading…"; el.setAttribute("aria-busy","true"); }')
        self.assertTrue(pagination.find_load_more_control(driver)['busy'])
        runtime=SimpleNamespace(store_page_limit=None,max_pages_per_keyword=2,page_timeout=1,safety=None)
        for kind in ('storefront','keyword_search'):
            with patch.object(front,'find_next_page_url',return_value=None):
                task,reason=front.build_next_front_task(driver,runtime,{'source_type':kind,'page_number':1,'page_url':driver.current_url},[{'asin':'B000000001'}])
            self.assertTrue(task);self.assertEqual(reason,'')
        driver.click_result_control=lambda *_:self.fail('busy more control must not be clicked')
        with patch.object(shared,'safety_before_remote_action'), patch.object(shared,'prepare_navigation'):
            with self.assertRaises(shared.WebDriverException):pagination.click_and_wait_more(driver,runtime)
        self.page.locator('#more').evaluate('el => { el.removeAttribute("aria-busy"); el.disabled=true; }')
        self.assertTrue(pagination.find_load_more_control(driver)['disabled'])

    def test_more_controls_in_empty_widgets_and_accessible_submit_wrappers(self):
        import result_pagination as pagination
        for control in (
            '<button id="more">Show more results</button>',
            '<input id="more" type="submit" aria-labelledby="more-label"><span id="more-label">Show more results</span>',
            '<span role="button"><button id="more">Show more results</button></span>',
        ):
            driver=self.driver('<div id="search"><div class="s-main-slot"><div class="s-result-item" data-asin="B000000001"><button>Show more results</button></div><div class="s-result-item" data-asin="">'+control+'</div></div></div>')
            found=pagination.find_load_more_control(driver)
            self.assertIsNotNone(found)
            self.assertEqual(self.page.locator(found['selector']).get_attribute('id'),'more')
            self.page.evaluate('document.querySelector("#more").onclick = () => document.querySelector(".s-main-slot").insertAdjacentHTML("beforeend", `<div class="s-result-item" data-asin="B000000002"></div>`);')
            self.page.locator(found['selector']).click()
            self.assertIn('B000000002',pagination.result_asins(driver))
        driver=self.driver('<div id="search"><button>Show more results</button><button>Show more results</button></div>')
        with self.assertRaises(shared.WebDriverException): pagination.find_load_more_control(driver)

    def test_more_button_scope_append_and_virtualized_replacement(self):
        import result_pagination as pagination
        for replacement in (False, True):
            html = '<div id="search"><div class="s-main-slot"><div class="s-result-item" data-asin="B000000001"><h2>First product</h2><button>Show more results</button></div></div><aside><button>Show more results</button></aside><button id="more">Show more results</button></div>'
            driver = self.driver(html)
            driver.click_result_control = lambda selector: self.page.locator(selector).click()
            self.page.evaluate('replace => { document.querySelector("#more").onclick = () => { const root=document.querySelector(".s-main-slot"); if(replace)root.innerHTML=""; root.insertAdjacentHTML("beforeend", `<div class="s-result-item" data-asin="B000000002"><h2>Second product</h2></div>`); document.querySelector("#more").remove(); }; }', replacement)
            self.assertIsNotNone(pagination.find_load_more_control(driver))
            runtime=SimpleNamespace(page_timeout=5, safety=None)
            with patch.object(shared, 'inspect_sellersprite_block', return_value={'status':'data_loading'}):
                after=pagination.click_and_wait_more(driver, runtime)
            self.assertIn('B000000002', after)
            self.assertIsNone(pagination.find_load_more_control(driver))
            driver._lc_seen_batch_asins=['B000000001']
            driver._lc_batch_asins=['B000000002']
            # A card appearing after the initial growth confirmation must join this batch.
            self.page.locator('.s-main-slot').evaluate('el => el.insertAdjacentHTML("beforeend", `<div class="s-result-item" data-asin="B000000003"><h2>Third product</h2></div>`)')
            self.assertEqual({c['asin'] for c in front.extract_front_product_cards(driver, True)}, {'B000000002','B000000003'})


if __name__ == "__main__":
    unittest.main()
