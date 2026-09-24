from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import amazon_image_competitor_crawler as image
from amazon_page_recovery import TransientAmazonPageUnavailable


class SourceImageRecoveryTests(unittest.TestCase):
    def runtime(self) -> SimpleNamespace:
        return SimpleNamespace(marketplace_domain="amazon.com", page_timeout=0.1)

    def test_extension_logo_is_not_downloaded(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(image.requests, "get") as request:
                with self.assertRaises(image.UserFacingError):
                    image.download_image(
                        "chrome-extension://seller-sprite/assets/header-logo.png",
                        Path(temp),
                        "source",
                    )
            request.assert_not_called()

    def test_saved_extension_url_is_replaced_by_real_product_image(self) -> None:
        current = {
            "source_id": "B000000001#row-4",
            "source_asin": "B000000001",
            "source_product_url": "https://www.amazon.com/dp/B000000001",
            "input_image_url": "chrome-extension://seller-sprite/assets/header-logo.png",
        }
        saved = []
        state = SimpleNamespace(set_current=lambda item: saved.append(dict(item)))
        image_url = "https://m.media-amazon.com/images/I/product.jpg"
        image_path = Path("/tmp/source.jpg")
        with patch.object(image, "load_source_product_main_image", return_value=image_url) as load:
            with patch.object(image, "download_image", return_value=image_path) as download:
                result = image.resolve_source_image(object(), self.runtime(), current, Path("/tmp"), state)
        self.assertEqual(result, image_path)
        self.assertEqual(current["input_image_url"], image_url)
        self.assertEqual(saved[-1]["input_image_url"], image_url)
        load.assert_called_once()
        download.assert_called_once_with(image_url, Path("/tmp"), current["source_id"])

    def test_dog_page_uses_canonical_url_for_same_asin(self) -> None:
        tracking_url = "https://www.amazon.com/product-name/dp/B000000001/ref=sr_1?tracking=old"
        canonical_url = "https://www.amazon.com/dp/B000000001"
        current = {
            "source_id": "B000000001#row-4",
            "source_asin": "B000000001",
            "source_product_url": tracking_url,
        }
        saved = []
        state = SimpleNamespace(set_current=lambda item: saved.append(dict(item)))
        image_url = "https://m.media-amazon.com/images/I/product.jpg"
        dog = TransientAmazonPageUnavailable("amazon_dog_error", reason="amazon_dog_error")
        with patch.object(image, "load_source_product_main_image", side_effect=[dog, image_url]) as load:
            with patch.object(image, "download_image", return_value=Path("/tmp/source.jpg")):
                image.resolve_source_image(object(), self.runtime(), current, Path("/tmp"), state)
        self.assertEqual([call.args[2] for call in load.call_args_list], [tracking_url, canonical_url])
        self.assertEqual(current["source_product_url"], tracking_url)
        self.assertEqual(current["source_image_page_url"], canonical_url)
        self.assertEqual(saved[-1]["input_image_url"], image_url)

    def test_dog_page_is_rejected_before_logo_can_be_used_as_product_image(self) -> None:
        driver = SimpleNamespace(
            title="Page Not Found",
            current_url="https://www.amazon.com/dp/B000000001",
            execute_script=lambda _script: "",
        )
        self.assertEqual(
            image.assess_image_page(driver, "product", expected_content_present=True).reason,
            "amazon_dog_error",
        )
        with patch.object(image, "open_image_amazon_page"):
            with patch.object(image, "extract_main_image_url") as extract:
                with self.assertRaises(image.SourceProductUnavailable) as raised:
                    image.load_source_product_main_image(
                        driver, self.runtime(), driver.current_url, None
                    )
        self.assertEqual(raised.exception.url, driver.current_url)
        extract.assert_not_called()

    def test_page_not_found_from_initial_navigation_is_skipped(self) -> None:
        driver = SimpleNamespace(title="Page Not Found")
        missing = TransientAmazonPageUnavailable("not found", reason="amazon_dog_error")
        with patch.object(image, "open_image_amazon_page", side_effect=missing):
            with self.assertRaises(image.SourceProductUnavailable):
                image.load_source_product_main_image(
                    driver, self.runtime(), "https://www.amazon.com/dp/B000000001", None
                )

    def test_confirmed_missing_tracking_and_canonical_pages_do_not_download_image(self) -> None:
        tracking_url = "https://www.amazon.com/example/dp/B000000001/ref=search"
        canonical_url = "https://www.amazon.com/dp/B000000001"
        current = {
            "source_id": "B000000001#row-4",
            "source_asin": "B000000001",
            "source_product_url": tracking_url,
        }
        state = SimpleNamespace(set_current=lambda _item: None)
        with patch.object(image, "load_source_product_main_image", side_effect=[
            image.SourceProductUnavailable(tracking_url),
            image.SourceProductUnavailable(canonical_url),
        ]) as load:
            with patch.object(image, "download_image") as download:
                with self.assertRaises(image.SourceProductUnavailable):
                    image.resolve_source_image(object(), self.runtime(), current, Path("/tmp"), state)
        self.assertEqual([call.args[2] for call in load.call_args_list], [tracking_url, canonical_url])
        download.assert_not_called()

    def test_unavailable_count_result_is_blank_and_has_reason(self) -> None:
        runtime = SimpleNamespace(match_mode="cascade", max_candidates_per_source=20)
        current = {"source_id": "B000000001#row-4", "input_row": 4}
        evaluation = image.MatchEvaluation([], {}, "", "source_unavailable", None, "", "商品页已失效")
        row = image.build_count_result_row(runtime, current, "", "", 0, evaluation)
        self.assertIsNone(row["same_product_count"])
        self.assertEqual(row["processing_status"], "source_unavailable")
        self.assertEqual(row["match_reason"], "商品页已失效")
        self.assertEqual(row[image.MINI_CONFIRMED_COUNT_FIELD], "")

    def test_lens_delivery_health_waits_for_async_file_input(self) -> None:
        driver = SimpleNamespace(
            title="Welcome to Shop the Look",
            current_url="https://www.amazon.com/products?searchtype=flow&modes=stylesnap",
            execute_script=lambda _script: "Shop the Look",
        )
        with patch.object(image, "image_expected_content_present", side_effect=[False, True]) as present:
            outcome = image.validate_image_delivery_page(
                driver, self.runtime(), None, "lens_upload"
            )
        self.assertEqual(outcome, "healthy")
        self.assertEqual(present.call_count, 2)


if __name__ == "__main__":
    unittest.main()
