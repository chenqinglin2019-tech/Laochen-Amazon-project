"""V8 main image: white by construction, verified on the decoded JPEG."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import studio_main as sm


def scene(backdrop=(255, 255, 255), product=(30, 30, 34), *, shadow=None, vignette=False, size=1024, hole=False):
    image = Image.new("RGB", (size, size), backdrop)
    array = np.asarray(image, np.float32)
    if vignette:
        yy, xx = np.mgrid[0:size, 0:size] / (size - 1) - 0.5
        array *= (1 - 0.15 * (xx ** 2 + yy ** 2) / 0.5)[..., None]
    if shadow:
        mask = Image.new("L", (size, size), 0)
        d = ImageDraw.Draw(mask)
        if shadow == "soft":
            d.ellipse((260, 840, 760, 920), fill=255)
            mask = mask.filter(ImageFilter.GaussianBlur(22))
            strength = 0.32
        else:
            d.rectangle((300, 860, 790, 920), fill=255)
            strength = 0.25
        array *= (1 - strength * np.asarray(mask, np.float32) / 255.0)[..., None]
    image = Image.fromarray(np.clip(array, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(image)
    d.rounded_rectangle((240, 160, 780, 880), 40, fill=product)
    if hole:
        d.ellipse((600, 400, 760, 600), fill=backdrop)
    return image


class CutoutTests(unittest.TestCase):
    def test_clean_vignette_and_soft_shadow_cut_out_exactly(self):
        for kwargs in ({}, {"vignette": True}, {"shadow": "soft"}):
            with self.subTest(**kwargs):
                foreground, matte, info = sm.cutout(scene(**kwargs))
                predicted = np.asarray(matte) > 127
                truth = np.zeros_like(predicted)
                truth[160:881, 240:781] = True
                iou = (predicted & truth).sum() / (predicted | truth).sum()
                self.assertGreater(iou, 0.97, info)

    def test_hard_shadow_is_refused_not_kept(self):
        with self.assertRaises(sm.MainError) as raised:
            sm.cutout(scene(shadow="hard"))
        self.assertEqual(raised.exception.code, "MAIN_SHADOW_AMBIGUOUS")

    def test_busy_background_and_cropped_product_are_refused(self):
        busy = scene()
        draw = ImageDraw.Draw(busy)
        for x in range(0, 1024, 30):
            draw.line((x, 0, x + 200, 1024), fill=(x % 200, 120, 90), width=9)
        with self.assertRaises(sm.MainError) as raised:
            sm.cutout(busy)
        self.assertEqual(raised.exception.code, "MAIN_BACKGROUND_NOT_PLAIN")
        cropped = Image.new("RGB", (1024, 1024), (255, 255, 255))
        ImageDraw.Draw(cropped).rectangle((-20, 100, 600, 900), fill=(20, 20, 20))
        with self.assertRaises(sm.MainError) as raised:
            sm.cutout(cropped)
        self.assertEqual(raised.exception.code, "MAIN_PRODUCT_CROPPED")

    def test_hole_on_grey_backdrop_becomes_background(self):
        foreground, matte, info = sm.cutout(scene(backdrop=(140, 140, 140), product=(245, 245, 245), hole=True))
        self.assertGreaterEqual(info["holes_removed"], 1)
        self.assertLess(np.asarray(matte)[500, 680], 10)

    def test_embedded_alpha_is_trusted(self):
        rgba = Image.new("RGBA", (800, 800), (0, 0, 0, 0))
        ImageDraw.Draw(rgba).ellipse((200, 150, 600, 650), fill=(200, 30, 40, 255))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "cut.png"
            rgba.save(path)
            image, alpha = sm.open_normalized(path)
            self.assertIsNotNone(alpha)
            _, matte, info = sm.cutout(image, alpha=alpha)
            self.assertEqual(info["method"], "embedded_alpha")


class ComposeVerifyTests(unittest.TestCase):
    def test_composite_is_exact_255_outside_the_product_and_fills_85_percent(self):
        foreground, matte, _ = sm.cutout(scene(backdrop=(200, 200, 200), product=(200, 40, 40)))
        result, placed, info = sm.compose(foreground, matte, (2000, 2000))
        self.assertAlmostEqual(info["fill"], 0.85, places=2)
        array = np.asarray(result)
        self.assertTrue((array[~placed] == 255).all())
        with tempfile.TemporaryDirectory() as temp:
            exported = sm.export(result, placed, Path(temp) / "main.jpg")
            self.assertEqual(exported["format"], "jpeg")
            self.assertTrue(exported["verify"]["ok"], exported["verify"])

    def test_verification_detects_a_single_off_white_pixel(self):
        foreground, matte, _ = sm.cutout(scene())
        result, placed, _ = sm.compose(foreground, matte, (2000, 2000))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.png"
            broken = result.copy()
            broken.putpixel((20, 20), (254, 255, 255))
            broken.save(path)
            report = sm.verify_jpeg(path, placed)
            self.assertFalse(report["ok"])
            self.assertEqual(report["background_blocks_bad"], 1)

    def test_too_small_product_is_refused(self):
        tiny = Image.new("RGB", (1024, 1024), (255, 255, 255))
        ImageDraw.Draw(tiny).rectangle((480, 480, 560, 560), fill=(10, 10, 10))
        foreground, matte, _ = sm.cutout(tiny)
        with self.assertRaises(sm.MainError) as raised:
            sm.compose(foreground, matte, (2000, 2000), max_upscale=sm.GENERATED_MAX_UPSCALE)
        self.assertEqual(raised.exception.code, "MAIN_PRODUCT_TOO_SMALL")


class BackdropChoiceTests(unittest.TestCase):
    def photo(self, colour):
        image = Image.new("RGB", (900, 900), (248, 248, 248))
        ImageDraw.Draw(image).rounded_rectangle((250, 150, 650, 750), 30, fill=colour)
        return image, None

    def test_white_or_light_products_get_grey_dark_products_get_white(self):
        self.assertEqual(sm.choose_backdrop([self.photo((245, 245, 245))])["backdrop"], "mid_grey")
        self.assertEqual(sm.choose_backdrop([self.photo((200, 200, 202))])["backdrop"], "mid_grey")
        self.assertEqual(sm.choose_backdrop([self.photo((25, 25, 28))])["backdrop"], "white")
        self.assertEqual(sm.choose_backdrop([self.photo((200, 30, 40))])["backdrop"], "white")
        self.assertEqual(sm.choose_backdrop([self.photo((245, 245, 245))], transparent=True)["backdrop"], "white")


class PhotoRouteTests(unittest.TestCase):
    def test_any_plain_backdrop_photo_qualifies_and_lifestyle_does_not(self):
        with tempfile.TemporaryDirectory() as temp:
            grey = Path(temp) / "grey.jpg"
            image = Image.new("RGB", (3000, 3000), (180, 182, 185))
            ImageDraw.Draw(image).rounded_rectangle((900, 600, 2100, 2400), 60, fill=(30, 60, 140))
            image.save(grey, quality=92)
            self.assertTrue(sm.photo_candidate(grey)["eligible"])
            busy = Path(temp) / "busy.jpg"
            image = Image.new("RGB", (3000, 3000), (120, 100, 80))
            draw = ImageDraw.Draw(image)
            for y in range(0, 3000, 50):
                draw.line((0, y, 3000, y + 400), fill=(160 + y % 90, 110, 70), width=20)
            draw.rounded_rectangle((900, 600, 2100, 2400), 60, fill=(30, 60, 140))
            image.save(busy, quality=92)
            self.assertFalse(sm.photo_candidate(busy)["eligible"])
            out = Path(temp) / "final.jpg"
            result = sm.build_from_photo(grey, out)
            self.assertTrue(result["verify"]["ok"])


if __name__ == "__main__":
    unittest.main()
