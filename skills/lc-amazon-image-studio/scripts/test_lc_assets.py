"""Compositing and embedded Amazon disclosure integration regressions."""
from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw, PngImagePlugin

import lc_assets as assets


class ProductCompositionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        # 1000x500 fully occupied opaque rectangle inside transparent asset border.
        self.product = Image.new("RGBA", (1200, 700), (0, 0, 0, 0))
        draw = ImageDraw.Draw(self.product)
        draw.rectangle((100, 100, 1099, 599), fill=(37, 92, 163, 255))
        # A genuine product marking whose pixel identity can be checked.
        draw.rectangle((480, 280, 519, 319), fill=(215, 69, 35, 255))
        self.product.save(self.base / "product.png")
        self.manifest = {"references": [{"id": "front", "path": "product.png"}]}
        self.job = {"canvas": [2000, 2600], "target_product_bbox_norm": [0.2, 0.2, 0.6, 0.6],
                    "product_layers": [{"reference_id": "front", "asset_origin": "original"}]}

    def tearDown(self):
        self.temp.cleanup()

    def test_high_resolution_alpha_composite_keeps_ratio_and_actual_bbox(self):
        output, provenance = assets.compose_product_layers(self.manifest, self.job, self.base)
        self.assertEqual((2000, 2600), output.size)
        self.assertEqual("RGB", output.mode)
        info = provenance[0]
        self.assertEqual(1.0, info["scale"])
        # Available target is 1200x1560, actual product is 1000x500 (2:1).
        x, y, w, h = info["bbox_norm"]
        self.assertAlmostEqual(2, (w * 2000) / (h * 2600))
        self.assertAlmostEqual(0.25, x)
        self.assertEqual((37, 92, 163), output.getpixel((round(x * 2000 + 50), round(y * 2600 + 50))))
        self.assertEqual((255, 255, 255), output.getpixel((0, 0)))

    def test_unit_scale_preserves_every_opaque_source_pixel(self):
        output, provenance = assets.compose_product_layers(self.manifest, self.job, self.base)
        info = provenance[0]
        left = round(info["bbox_norm"][0] * output.width)
        top = round(info["bbox_norm"][1] * output.height)
        actual = output.crop((left, top, left + 1000, top + 500))
        source = self.product.crop((100, 100, 1100, 600)).convert("RGB")
        self.assertEqual(assets.pixel_hash(source), assets.pixel_hash(actual))
        self.assertEqual(assets.file_hash(self.base / "product.png"), info["asset_sha256"])
        self.assertEqual(["front"], info["source_reference_ids"])

    def test_mask_dimensions_must_match(self):
        Image.new("L", (120, 70), 255).save(self.base / "bad_mask.png")
        self.job["product_layers"][0]["mask_path"] = "bad_mask.png"
        with self.assertRaisesRegex(ValueError, "mask size must match"):
            assets.compose_product_layers(self.manifest, self.job, self.base)

    def test_mask_application_and_provenance(self):
        self.product.convert("RGB").save(self.base / "opaque.png")
        self.product.getchannel("A").save(self.base / "mask.png")
        layer = self.job["product_layers"][0]
        layer.update(asset_path="opaque.png", mask_path="mask.png")
        output, provenance = assets.compose_product_layers(self.manifest, self.job, self.base)
        self.assertEqual(assets.file_hash(self.base / "mask.png"), provenance[0]["mask_sha256"])
        self.assertEqual((255, 255, 255), output.getpixel((0, 0)))

    def test_opaque_rectangle_requires_explicit_review(self):
        self.product.convert("RGB").save(self.base / "opaque.png")
        layer = self.job["product_layers"][0]
        layer["asset_path"] = "opaque.png"
        with self.assertRaisesRegex(ValueError, "reviewed mask"):
            assets.compose_product_layers(self.manifest, self.job, self.base)
        layer["opaque_rectangle"] = True
        output, _ = assets.compose_product_layers(self.manifest, self.job, self.base)
        self.assertEqual((2000, 2600), output.size)

    def test_empty_alpha_and_empty_crops_are_rejected(self):
        Image.new("RGBA", (1200, 700), (0, 0, 0, 0)).save(self.base / "empty.png")
        self.job["product_layers"][0]["asset_path"] = "empty.png"
        with self.assertRaisesRegex(ValueError, "empty or fully transparent"):
            assets.compose_product_layers(self.manifest, self.job, self.base)

    def test_out_of_bounds_product_never_silently_crops(self):
        for box in ([0.8, 0.2, 0.4, 0.4], [-0.1, 0, 0.5, 0.5], [0, 0, float("nan"), 0.5], [0, 0, 0, 1]):
            with self.subTest(box=box):
                self.job["product_layers"][0]["bbox_norm"] = box
                with self.assertRaises(ValueError):
                    assets.compose_product_layers(self.manifest, self.job, self.base)

    def test_missing_layers_and_unknown_reference_rejected(self):
        self.job["product_layers"] = []
        with self.assertRaisesRegex(ValueError, "requires product_layers"):
            assets.compose_product_layers(self.manifest, self.job, self.base)
        self.job["product_layers"] = [{"reference_id": "missing"}]
        with self.assertRaisesRegex(ValueError, "reference_id is unknown"):
            assets.compose_product_layers(self.manifest, self.job, self.base)

    def test_contact_shadow_changes_background_without_changing_product(self):
        plain, _ = assets.compose_product_layers(self.manifest, self.job, self.base)
        self.job["product_layers"][0]["shadow"] = {"enabled": True, "opacity": 0.4, "blur": 15, "offset": [0, 25]}
        shadowed, provenance = assets.compose_product_layers(self.manifest, self.job, self.base)
        self.assertNotEqual(assets.pixel_hash(plain), assets.pixel_hash(shadowed))
        x, y, w, h = provenance[0]["bbox_norm"]
        rect = (round(x * plain.width), round(y * plain.height), round((x + w) * plain.width), round((y + h) * plain.height))
        self.assertEqual(assets.pixel_hash(plain.crop(rect)), assets.pixel_hash(shadowed.crop(rect)))

    def test_generated_and_restored_origins_inherit_without_becoming_original(self):
        self.job["product_layers"][0].pop("asset_origin")
        for origin in ("generated", "restored"):
            with self.subTest(origin=origin):
                self.manifest["references"][0]["provenance"] = {"kind": origin, "source_reference_ids": ["real_front", "real_side"]}
                _, provenance = assets.compose_product_layers(self.manifest, self.job, self.base)
                self.assertEqual(origin, provenance[0]["asset_origin"])
                self.assertEqual(["front", "real_front", "real_side"], provenance[0]["source_reference_ids"])

    def test_explicit_source_ids_retain_reference_and_real_evidence(self):
        self.job["product_layers"][0].pop("asset_origin")
        self.job["product_layers"][0]["source_reference_ids"] = ["closeup"]
        self.manifest["references"][0]["provenance"] = {"kind": "generated", "source_reference_ids": ["real_front"]}
        _, provenance = assets.compose_product_layers(self.manifest, self.job, self.base)
        self.assertEqual(["front", "closeup", "real_front"], provenance[0]["source_reference_ids"])

    def test_generated_reference_cannot_log_original_pixels(self):
        self.manifest["references"][0]["provenance"] = {"kind": "generated", "source_reference_ids": ["real_front"]}
        with self.assertRaisesRegex(ValueError, "asset_origin contradicts"):
            assets.compose_product_layers(self.manifest, self.job, self.base)

    def test_rgb_list_padding_and_shadow_colors_are_supported(self):
        self.job["padding_color"] = [246, 249, 251]
        self.job["product_layers"][0]["shadow"] = {"enabled": True, "color": [10, 20, 30]}
        image, provenance = assets.compose_product_layers(self.manifest, self.job, self.base)
        self.assertEqual((246, 249, 251), image.getpixel((0, 0)))
        self.assertEqual("original", provenance[0]["asset_origin"])


class DisclosureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.image = Image.new("RGB", (1600, 1600), (57, 103, 161))
        ImageDraw.Draw(self.image).rectangle((400, 400, 1100, 1100), fill=(130, 183, 49))
        self.job = {"kind": "listing", "canvas": [1600, 1600], "image_sha256": "reviewed-raw-stage-hash",
                    "ai_disclosure": {"human_source": "synthetic", "reviewed_image_sha256": "reviewed-raw-stage-hash"},
                    "export": {"keywords": ["product", "商品", "product"]}}

    def tearDown(self):
        self.temp.cleanup()

    def test_png_and_jpeg_embed_keywords_and_roundtrip(self):
        for suffix in (".png", ".jpg", ".jpeg"):
            with self.subTest(suffix=suffix):
                path = self.base / ("final" + suffix)
                result = assets.export_image(self.image, self.job, path)
                self.assertTrue(result["verified"])
                self.assertEqual(assets.file_hash(path), result["file_sha256"])
                with Image.open(path) as image:
                    self.assertEqual({assets.SYNTHETIC_KEYWORD, "product", "商品"}, set(assets.xmp_keywords(image)))
                    self.assertEqual((1600, 1600), image.size)
                    self.assertEqual("RGB", image.mode)
                self.assertEqual([], assets.check_export(self.job, path))
                self.assertFalse(path.with_name(path.name + ".tmp").exists())

    def test_png_metadata_changes_no_visible_pixels_or_watermark(self):
        path = self.base / "final.png"
        assets.export_image(self.image, self.job, path)
        with Image.open(path) as image:
            self.assertEqual(assets.pixel_hash(self.image), assets.pixel_hash(image))
        # Changing disclosure only keeps identical visual pixels.
        self.job["ai_disclosure"]["human_source"] = "none"
        assets.export_image(self.image, self.job, path)
        with Image.open(path) as image:
            self.assertEqual(assets.pixel_hash(self.image), assets.pixel_hash(image))
            self.assertNotIn(assets.SYNTHETIC_KEYWORD, assets.xmp_keywords(image))

    def test_keyword_idempotence_on_repeated_export(self):
        self.job["export"]["keywords"] += [assets.SYNTHETIC_KEYWORD, assets.SYNTHETIC_KEYWORD]
        path = self.base / "final.png"
        first = assets.export_image(self.image, self.job, path)
        second = assets.export_image(self.image, self.job, path)
        self.assertEqual(first["file_sha256"], second["file_sha256"])
        self.assertEqual(1, second["embedded_keywords"].count(assets.SYNTHETIC_KEYWORD))

    def test_review_required_and_bound_to_image(self):
        for data, expected in (({}, "AI_HUMAN_SOURCE_REVIEW_REQUIRED"),
                               ({"human_source": "synthetic", "reviewed_image_sha256": "old"}, "AI_DISCLOSURE_NOT_BOUND_TO_IMAGE"),
                               (None, "AI_HUMAN_SOURCE_REVIEW_REQUIRED"),
                               ({"human_source": []}, "AI_HUMAN_SOURCE_REVIEW_REQUIRED")):
            with self.subTest(data=data):
                job = copy.deepcopy(self.job)
                job["ai_disclosure"] = data
                path = self.base / "never-created.png"
                with self.assertRaisesRegex(ValueError, expected):
                    assets.export_image(self.image, job, path)
                self.assertFalse(path.exists())

    def test_no_human_real_and_nonphotorealistic_do_not_get_performer_tag(self):
        for human_source in ("none", "real", "non_photorealistic"):
            with self.subTest(human_source=human_source):
                self.job["ai_disclosure"]["human_source"] = human_source
                # User keywords cannot override the reviewed human classification.
                self.job["export"]["keywords"] = [assets.SYNTHETIC_KEYWORD, "product"]
                path = self.base / (human_source + ".png")
                assets.export_image(self.image, self.job, path)
                with Image.open(path) as image:
                    self.assertNotIn(assets.SYNTHETIC_KEYWORD, assets.xmp_keywords(image))
                self.assertEqual([], assets.check_export(self.job, path))

    def test_ad_needs_channel_specific_review(self):
        self.job["kind"] = "ad"
        with self.assertRaisesRegex(ValueError, "AD_CHANNEL_DISCLOSURE_REVIEW_REQUIRED"):
            assets.export_image(self.image, self.job, self.base / "ad.png")
        self.job["ai_disclosure"]["channel_reviewed"] = True
        assets.export_image(self.image, self.job, self.base / "ad.png")

    def test_malformed_and_external_entity_metadata_rejected(self):
        for payload in ("<broken", '<!DOCTYPE doc [<!ENTITY x "evil">]><doc/>'):
            with self.subTest(payload=payload):
                info = PngImagePlugin.PngInfo()
                info.add_itxt("XML:com.adobe.xmp", payload)
                path = self.base / "invalid.png"
                self.image.save(path, pnginfo=info)
                errors = assets.check_export(self.job, path)
                self.assertTrue(any(error.startswith("EXPORT_UNREADABLE:") for error in errors))

    def test_removed_or_wrong_metadata_is_rejected(self):
        path = self.base / "stripped.png"
        self.image.save(path)
        self.assertIn("SYNTHETIC_PERFORMER_METADATA_MISMATCH", assets.check_export(self.job, path))
        assets.export_image(self.image, self.job, path)
        self.job["ai_disclosure"]["human_source"] = "none"
        self.assertIn("SYNTHETIC_PERFORMER_METADATA_MISMATCH", assets.check_export(self.job, path))

    def test_invalid_image_and_wrong_size_are_rejected(self):
        path = self.base / "invalid.png"
        path.write_bytes(b"not an image")
        self.assertTrue(any(error.startswith("EXPORT_UNREADABLE:") for error in assets.check_export(self.job, path)))
        Image.new("RGB", (100, 100)).save(path)
        self.assertIn("EXPORT_SIZE_MISMATCH", assets.check_export(self.job, path))

    def test_failed_metadata_roundtrip_cannot_replace_good_output(self):
        path = self.base / "final.png"
        assets.export_image(self.image, self.job, path)
        previous = assets.file_hash(path)
        with patch.object(assets, "xmp_keywords", return_value=[]):
            with self.assertRaisesRegex(ValueError, "round-trip"):
                assets.export_image(self.image, self.job, path)
        self.assertEqual(previous, assets.file_hash(path))
        self.assertFalse(path.with_name(path.name + ".tmp").exists())

    def test_export_size_mismatch_does_not_write_deliverable(self):
        path = self.base / "wrong.png"
        with self.assertRaisesRegex(ValueError, "EXPORT_SIZE_MISMATCH"):
            assets.export_image(Image.new("RGB", (100, 100)), self.job, path)
        self.assertFalse(path.exists())

    def test_check_export_handles_null_disclosure(self):
        path = self.base / "final.png"
        assets.export_image(self.image, self.job, path)
        self.job["ai_disclosure"] = None
        self.assertIn("AI_HUMAN_SOURCE_REVIEW_REQUIRED", assets.check_export(self.job, path))

    def test_export_does_not_copy_obsolete_xmp_signature_or_keywords(self):
        self.image.info["xmp"] = b"<obsolete-c2pa-or-signature/>"
        result = assets.export_image(self.image, self.job, self.base / "final.png")
        self.assertIn("not_reissued", result["c2pa"])
        with Image.open(self.base / "final.png") as image:
            payload = image.info.get("XML:com.adobe.xmp", "")
            self.assertNotIn("obsolete", payload)

    def test_remote_asset_rejected(self):
        with self.assertRaisesRegex(ValueError, "Only local"):
            assets.local_asset("https://example.com/product.png", self.base)


if __name__ == "__main__":
    unittest.main()
