from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import MagicMock, patch


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import amazon_image_competitor_crawler as image


class SwitchDriver:
    def __init__(
        self,
        urls_by_handle: dict[str, str],
        *,
        active_handle: str,
        owned_handles: set[str] | None = None,
    ) -> None:
        self._urls_by_handle = dict(urls_by_handle)
        self._active_handle = active_handle
        self._owned_handles = set(owned_handles or {active_handle})
        self.closed_handles: list[str] = []
        self.registered_handles: list[str] = []
        self._action_candidates: dict[str, set[str]] = {}
        self.switch_to = SimpleNamespace(window=self._switch_window)

    @property
    def window_handles(self) -> list[str]:
        return list(self._urls_by_handle)

    @property
    def current_url(self) -> str:
        return self._urls_by_handle[self._active_handle]

    @property
    def current_window_handle(self) -> str:
        return self._active_handle

    def _switch_window(self, handle: str) -> None:
        self._active_handle = handle

    def register_owned_window_handle(self, handle: str) -> None:
        self.registered_handles.append(handle)
        self._owned_handles.add(handle)

    def owned_handle_snapshot(self) -> frozenset[str]:
        return frozenset(
            handle for handle in self._owned_handles if handle in self._urls_by_handle
        )

    def emit_owned_popup(self, handle: str) -> None:
        self._owned_handles.add(handle)

    def begin_owned_page_action(self, label: str = "") -> str:
        token = f"{label}:token"
        self._action_candidates[token] = set()
        return token

    def emit_action_page(self, handle: str, url: str) -> None:
        self._urls_by_handle[handle] = url
        for candidates in self._action_candidates.values():
            candidates.add(handle)

    def claim_owned_action_pages(self, token: str, predicate: object) -> list[str]:
        claimed = []
        for handle in self._action_candidates.get(token, set()):
            if predicate(self._urls_by_handle[handle]):  # type: ignore[operator]
                self._owned_handles.add(handle)
                claimed.append(handle)
        return claimed

    def end_owned_page_action(self, token: str) -> None:
        self._action_candidates.pop(token, None)

    def close_owned_since(self, snapshot: frozenset[str]) -> int:
        targets = [
            handle
            for handle in self.window_handles
            if handle in self._owned_handles and handle not in snapshot
        ]
        for handle in targets:
            self._switch_window(handle)
            self.close()
        self.restore_worker_page()
        return len(targets)

    def restore_worker_page(self) -> str:
        worker = next(
            handle
            for handle in self._owned_handles
            if handle in self._urls_by_handle
        )
        self._switch_window(worker)
        return worker

    def close(self) -> None:
        handle = self._active_handle
        self.closed_handles.append(handle)
        self._urls_by_handle.pop(handle, None)
        if self._urls_by_handle:
            self._active_handle = next(iter(self._urls_by_handle))


class FindSimilarResultSafetyTests(unittest.TestCase):
    def test_product_detail_cards_never_count_as_find_similar_result(self) -> None:
        driver = SwitchDriver(
            {"source": "https://www.amazon.com/dp/B000000001"},
            active_handle="source",
        )
        recommendation_or_variant_cards = [
            {
                "asin": "B000000002",
                "candidate_image_url": "https://m.media-amazon.com/images/I/recommendation.jpg",
            }
        ]

        with patch.object(
            image,
            "extract_lens_candidate_cards",
            return_value=recommendation_or_variant_cards,
        ):
            self.assertFalse(
                image.switch_to_find_similar_result(driver, {"source"}),
                "商品详情页里的推荐/变体 data-asin 不能伪装成以图搜图结果页",
            )

    def test_new_product_detail_tab_is_not_a_find_similar_result(self) -> None:
        product_urls = (
            "https://www.amazon.com/dp/B000000002?ref_=find_similar",
            "https://www.amazon.com/dp/B000000002?ref_=stylesnap",
            "https://www.amazon.com/dp/B000000002?searchtype=flow",
        )
        for product_url in product_urls:
            with self.subTest(product_url=product_url):
                driver = SwitchDriver(
                    {
                        "source": "https://www.amazon.com/dp/B000000001",
                        "new": product_url,
                    },
                    active_handle="source",
                    owned_handles={"source", "new"},
                )

                with patch.object(
                    image,
                    "extract_lens_candidate_cards",
                    return_value=[{"asin": "B000000003"}],
                ):
                    self.assertFalse(
                        image.switch_to_find_similar_result(driver, {"source"}),
                        "商品详情 URL 即使含 Lens 查询词也不能被视为结果页",
                    )
                self.assertEqual(driver.current_url, product_url)

    def test_same_tab_or_new_tab_must_reach_a_known_lens_result_url(self) -> None:
        cases = (
            (
                {"source": "https://www.amazon.com/products?searchtype=flow"},
                "source",
                {"source"},
            ),
            (
                {"source": "https://www.amazon.com/products?modes=stylesnap"},
                "source",
                {"source"},
            ),
            (
                {
                    "source": "https://www.amazon.com/dp/B000000001",
                    "new": "https://www.amazon.com/products?searchtype=flow&modes=stylesnap",
                },
                "source",
                {"source"},
            ),
        )
        for urls, active_handle, before_handles in cases:
            with self.subTest(urls=urls):
                driver = SwitchDriver(
                    urls,
                    active_handle=active_handle,
                    owned_handles=set(urls),
                )
                self.assertTrue(image.switch_to_find_similar_result(driver, before_handles))

    def test_claimed_result_tab_is_closed_and_original_tabs_are_preserved(self) -> None:
        driver = SwitchDriver(
            {
                "source": "https://www.amazon.com/dp/B000000001",
                "user": "https://example.com/user-tab",
                "result": "https://www.amazon.com/stylesnap?q=local",
            },
            active_handle="source",
        )
        claimed_before = image.claimed_crawler_window_handles(driver)
        driver.emit_owned_popup("result")

        self.assertTrue(
            image.switch_to_find_similar_result(driver, {"source", "user"})
        )
        self.assertEqual(driver.current_window_handle, "result")

        self.assertEqual(
            image.close_claimed_crawler_windows(
                driver,
                claimed_before,
                ["user", "source"],
            ),
            1,
        )
        self.assertEqual(driver.current_window_handle, "source")
        self.assertEqual(set(driver.window_handles), {"source", "user"})
        self.assertEqual(driver.closed_handles, ["result"])

    def test_concurrent_unknown_user_tab_is_never_claimed_or_closed(self) -> None:
        driver = SwitchDriver(
            {
                "source": "https://www.amazon.com/dp/B000000001",
                "result": "https://www.amazon.com/products?searchtype=flow",
                "user": "https://example.com/opened-concurrently",
            },
            active_handle="source",
            owned_handles={"source"},
        )
        claimed_before = image.claimed_crawler_window_handles(driver)
        driver.emit_owned_popup("result")

        self.assertTrue(image.switch_to_find_similar_result(driver, claimed_before))
        image.close_claimed_crawler_windows(driver, claimed_before, ["source"])

        self.assertEqual(set(driver.window_handles), {"source", "user"})
        self.assertNotIn("user", driver.registered_handles)
        self.assertNotIn("user", driver.closed_handles)

    def test_production_switch_claims_action_scoped_noopener_only_on_marketplace(self) -> None:
        driver = SwitchDriver(
            {"source": "https://www.amazon.com/dp/B000000001"},
            active_handle="source",
        )
        claimed_before = image.claimed_crawler_window_handles(driver)
        token = image.begin_crawler_page_action(driver, "find-similar")
        driver.emit_action_page(
            "user",
            "https://example.com/stylesnap/products?searchType=flow",
        )
        driver.emit_action_page(
            "result",
            "https://www.amazon.com/stylesnap/products?searchType=flow",
        )

        self.assertTrue(
            image.switch_to_find_similar_result(
                driver,
                claimed_before,
                driver._urls_by_handle["source"],
                token,
                "amazon.com",
            )
        )
        image.end_crawler_page_action(driver, token)
        image.close_claimed_crawler_windows(driver, claimed_before, ["source"])

        self.assertNotIn("result", driver.window_handles)
        self.assertIn("user", driver.window_handles)
        self.assertNotIn("user", driver.closed_handles)


class SellerSpriteClickSafetyTests(unittest.TestCase):
    def test_image_sellersprite_block_preserves_amazon_sign_in_reason(self) -> None:
        driver = SimpleNamespace(
            current_url="https://www.amazon.com/ap/signin",
            _sellersprite_readiness={"blocked_reason": "amazon_sign_in"},
        )
        runtime = SimpleNamespace(manual_pause_timeout=900)
        with (
            patch.object(image, "wait_for_manual_clear", return_value=False) as clear,
            self.assertRaisesRegex(
                image.VerificationUnconfirmedError,
                "amazon_sign_in_terminal",
            ) as caught,
        ):
            image.handle_image_sellersprite_block(driver, runtime, None)
        clear.assert_not_called()
        self.assertNotIn("人工处理超时", str(caught.exception))

    def test_click_script_is_scoped_to_sellersprite_and_exact_find_similar_text(self) -> None:
        captured_scripts: list[str] = []

        class Driver:
            current_url = "https://www.amazon.com/dp/B000000001"
            window_handles = ["source"]

            def execute_script(self, script: str, *_args: object) -> bool:
                captured_scripts.append(script)
                return True

        class ImmediateWait:
            def __init__(self, *_args: object, **_kwargs: object) -> None:
                pass

            def until(self, _predicate: object) -> bool:
                return True

        runtime = SimpleNamespace(
            marketplace_domain="amazon.com",
            page_timeout=30,
            find_similar_timeout=12,
        )
        current = {
            "source_asin": "B000000001",
            "source_product_url": "https://www.amazon.com/dp/B000000001",
        }
        with (
            patch.object(image, "WebDriverWait", ImmediateWait),
            patch.object(image.time, "sleep"),
            patch.object(image, "handle_amazon_verification"),
            patch.object(image, "ensure_amazon_delivery_location"),
        ):
            self.assertTrue(
                image.trigger_sellersprite_find_similar(Driver(), runtime, current)
            )

        self.assertGreaterEqual(len(captured_scripts), 2)
        click_script = captured_scripts[-1]
        lowered = click_script.lower()
        self.assertTrue(
            "sellersprite" in lowered or "seller-sprite" in lowered,
            "找相似按钮必须先限定在 SellerSprite 插件容器内",
        )
        self.assertNotIn(
            "document.querySelectorAll('button,a,div,span')",
            click_script,
            "不得从整个 Amazon 页面扫描普通 Similar 区块",
        )
        self.assertIn("找相似", click_script)
        self.assertIn("find similar", lowered)
        self.assertNotRegex(lowered, r"\|\s*similar\s*\)")
        self.assertNotIn("item.text === 'similar'", lowered)

    def test_failed_temporary_popup_restores_original_live_tab(self) -> None:
        class Driver(SwitchDriver):
            def __init__(self) -> None:
                super().__init__(
                    {"source": "https://www.amazon.com/dp/B000000001"},
                    active_handle="source",
                )
                self.script_calls = 0

            def execute_script(self, _script: str, *_args: object) -> bool:
                self.script_calls += 1
                if self.script_calls == 2:
                    self._urls_by_handle["popup"] = (
                        "https://www.amazon.com/dp/B000000002?ref_=find_similar"
                    )
                    self.emit_owned_popup("popup")
                return True

        driver = Driver()

        class TwoStageWait:
            calls = 0

            def __init__(self, *_args: object, **_kwargs: object) -> None:
                pass

            def until(self, predicate: object) -> object:
                TwoStageWait.calls += 1
                if TwoStageWait.calls == 1:
                    return True
                predicate(driver)  # type: ignore[operator]
                driver._urls_by_handle.pop("popup", None)
                raise image.TimeoutException("find-similar popup closed")

        runtime = SimpleNamespace(
            marketplace_domain="amazon.com",
            page_timeout=30,
            find_similar_timeout=12,
        )
        current = {
            "source_asin": "B000000001",
            "source_product_url": "https://www.amazon.com/dp/B000000001",
        }
        with (
            patch.object(image, "WebDriverWait", TwoStageWait),
            patch.object(image.time, "sleep"),
        ):
            self.assertFalse(
                image.trigger_sellersprite_find_similar(driver, runtime, current)
            )
        self.assertEqual(driver.current_url, "https://www.amazon.com/dp/B000000001")

    def test_failed_persistent_popup_is_closed_before_upload_fallback(self) -> None:
        class Driver(SwitchDriver):
            def __init__(self) -> None:
                super().__init__(
                    {"source": "https://www.amazon.com/dp/B000000001"},
                    active_handle="source",
                )
                self.script_calls = 0

            def execute_script(self, _script: str, *_args: object) -> bool:
                self.script_calls += 1
                if self.script_calls == 2:
                    self._urls_by_handle["popup"] = (
                        "https://www.amazon.com/dp/B000000002?ref_=find_similar"
                    )
                    self.emit_owned_popup("popup")
                return True

        driver = Driver()

        class TwoStageWait:
            calls = 0

            def __init__(self, *_args: object, **_kwargs: object) -> None:
                pass

            def until(self, predicate: object) -> object:
                TwoStageWait.calls += 1
                if TwoStageWait.calls == 1:
                    return True
                predicate(driver)  # type: ignore[operator]
                raise image.TimeoutException("not a trusted Lens result")

        runtime = SimpleNamespace(
            marketplace_domain="amazon.com",
            page_timeout=30,
            find_similar_timeout=12,
        )
        current = {
            "source_asin": "B000000001",
            "source_product_url": "https://www.amazon.com/dp/B000000001",
        }
        with (
            patch.object(image, "WebDriverWait", TwoStageWait),
            patch.object(image.time, "sleep"),
        ):
            self.assertFalse(
                image.trigger_sellersprite_find_similar(driver, runtime, current)
            )

        self.assertEqual(driver.current_window_handle, "source")
        self.assertEqual(driver.window_handles, ["source"])
        self.assertEqual(driver.closed_handles, ["popup"])


class CandidateImageUrlSafetyTests(unittest.TestCase):
    def test_extraction_rejects_page_urls_but_keeps_real_image_and_image_data_urls(self) -> None:
        page_url = "https://www.amazon.com/dp/B000000001"
        raw_cards = [
            {"asin": "B000000001", "candidate_image_url": page_url},
            {
                "asin": "B000000002",
                "candidate_image_url": "https://www.amazon.com/gp/product/B000000002",
            },
            {
                "asin": "B000000003",
                "candidate_image_url": "https://m.media-amazon.com/images/I/real-image.jpg",
            },
            {
                "asin": "B000000004",
                "candidate_image_url": "data:image/png;base64,aGVsbG8=",
            },
            {
                "asin": "B000000005",
                "candidate_image_url": "data:text/html;base64,PGh0bWw+PC9odG1sPg==",
            },
        ]

        class Driver:
            current_url = page_url
            page_source = ""

            def execute_script(self, _script: str, _include_text: bool) -> list[dict[str, str]]:
                return raw_cards

        rows = image.extract_lens_candidate_cards(Driver(), include_text=False)
        by_asin = {str(row["asin"]): row for row in rows}

        for asin in ("B000000001", "B000000002", "B000000005"):
            self.assertTrue(
                asin not in by_asin or not by_asin[asin].get("candidate_image_url"),
                f"{asin} 的页面/非图片 URL 必须被拒绝",
            )
        self.assertEqual(
            by_asin["B000000003"]["candidate_image_url"],
            "https://m.media-amazon.com/images/I/real-image.jpg",
        )
        self.assertEqual(
            by_asin["B000000004"]["candidate_image_url"],
            "data:image/png;base64,aGVsbG8=",
        )

    def test_html_download_cannot_be_wrapped_as_an_image_data_url(self) -> None:
        response = MagicMock()
        response.headers = {"content-type": "text/html; charset=utf-8"}
        response.content = b"<html><title>Amazon error page</title></html>"
        response.raise_for_status.return_value = None

        with patch.object(image.requests, "get", return_value=response):
            with self.assertRaisesRegex(image.UserFacingError, "图片|image|Content-Type"):
                image.image_url_to_data_url(
                    "https://m.media-amazon.com/images/I/not-an-image.jpg"
                )


class LensNavigationRaceTests(unittest.TestCase):
    def test_safe_current_url_handles_closed_owned_tab(self) -> None:
        class ClosedDriver:
            @property
            def current_url(self) -> str:
                raise image.WebDriverException("CDP 抓取标签页已经关闭")

        self.assertEqual(image.safe_driver_current_url(ClosedDriver()), "")

    def test_open_page_retries_destroyed_navigation_context(self) -> None:
        runtime = SimpleNamespace(page_timeout=10)
        with (
            patch.object(
                image,
                "open_amazon_page",
                side_effect=[
                    image.WebDriverException(
                        "Page.evaluate: Execution context was destroyed, most likely because of a navigation"
                    ),
                    None,
                ],
            ) as open_page,
            patch.object(image.time, "sleep"),
        ):
            image.open_image_amazon_page(
                MagicMock(),
                "https://www.amazon.com/products?searchtype=flow",
                runtime,
            )
        self.assertEqual(open_page.call_count, 2)

    def test_upload_accepts_navigation_started_by_setting_file(self) -> None:
        element = MagicMock()
        element.send_keys.side_effect = image.WebDriverException(
            "Execution context was destroyed, most likely because of a navigation"
        )
        driver = MagicMock()
        driver.execute_script.return_value = True
        driver.find_element.return_value = element

        class ImmediateWait:
            def __init__(self, *_args: object, **_kwargs: object) -> None:
                pass

            def until(self, predicate: object) -> object:
                return predicate(driver)  # type: ignore[operator]

        runtime = SimpleNamespace(
            lens_url="https://www.amazon.com/products?searchtype=flow",
            page_timeout=10,
        )
        with (
            patch.object(image, "open_image_amazon_page"),
            patch.object(image, "WebDriverWait", ImmediateWait),
        ):
            image.upload_image_to_lens(
                driver,
                runtime,
                Path("/tmp/source.jpg"),
            )
        element.send_keys.assert_called_once()

    def test_block_detection_retries_destroyed_navigation_context(self) -> None:
        with (
            patch.object(
                image,
                "detect_block",
                side_effect=[
                    image.WebDriverException(
                        "Page.evaluate: Execution context was destroyed, most likely because of a navigation"
                    ),
                    None,
                ],
            ) as detect,
            patch.object(image.time, "sleep"),
        ):
            self.assertIsNone(image.detect_block_after_navigation(MagicMock(), 2))
        self.assertEqual(detect.call_count, 2)

    def test_block_detection_does_not_hide_non_navigation_errors(self) -> None:
        with patch.object(
            image,
            "detect_block",
            side_effect=image.WebDriverException("target page has been closed"),
        ):
            with self.assertRaisesRegex(image.WebDriverException, "closed"):
                image.detect_block_after_navigation(MagicMock(), 2)

    def test_controlled_upload_retry_waits_for_a_verified_lens_terminal_state(self) -> None:
        runtime = SimpleNamespace(page_timeout=30)
        driver = MagicMock()
        source_path = Path("/tmp/source.jpg")
        with (
            patch.object(image, "upload_image_to_lens") as upload,
            patch.object(image, "detect_block_after_navigation", return_value="") as block,
            patch.object(image, "wait_for_lens_results", return_value="results") as wait,
        ):
            self.assertEqual(
                image.upload_and_wait_for_lens_results(
                    driver,
                    runtime,
                    source_path,
                ),
                "results",
            )
        upload.assert_called_once_with(driver, runtime, source_path, None)
        block.assert_called_once_with(driver, 15)
        wait.assert_called_once_with(driver, runtime)


class LensExplicitEmptyResultTests(unittest.TestCase):
    def test_visible_no_styles_page_is_a_verified_empty_terminal_state(self) -> None:
        class Driver:
            current_url = "https://www.amazon.com/stylesnap?ref=mkt_lp_m_upload&q=local"

            def execute_script(self, _script: str, *_args: object) -> bool:
                return True

        class ImmediateWait:
            def __init__(self, *_args: object, **_kwargs: object) -> None:
                pass

            def until(self, predicate: object) -> object:
                return predicate(Driver())  # type: ignore[operator]

        runtime = SimpleNamespace(page_timeout=30, lens_results_timeout=30)
        with (
            patch.object(image, "WebDriverWait", ImmediateWait),
            patch.object(image, "extract_lens_candidate_cards", return_value=[]),
        ):
            self.assertEqual(
                image.wait_for_lens_results(Driver(), runtime),
                "no_results",
            )

    def test_empty_cards_without_explicit_no_result_do_not_become_zero(self) -> None:
        driver = MagicMock()
        driver.current_url = "https://www.amazon.com/stylesnap?q=local"
        driver.execute_script.return_value = False
        self.assertFalse(image.lens_no_results_visible(driver))


if __name__ == "__main__":
    unittest.main()
