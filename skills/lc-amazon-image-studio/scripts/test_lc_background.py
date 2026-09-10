import copy
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

import lc_background as background
from lc_assets import file_hash, pixel_hash


class BackgroundTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lc-background-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.image = Image.new("RGB", (32, 32), (254, 254, 254))
        self.protected = Image.new("L", self.image.size, 0)
        ImageDraw.Draw(self.protected).rectangle((10, 8, 21, 25), fill=255)
        self.allowed = Image.eval(self.protected, lambda value: 255 - value)
        self.job = {"kind": "main", "background_normalization": {
            "version": 1, "reviewed": True, "protection_covers_product_and_shadow": True,
            "source_pixel_sha256": pixel_hash(self.image),
            "background_mask": self.save_mask("allowed.png", self.allowed),
            "protection_mask": self.save_mask("protected.png", self.protected)}}

    def save_mask(self, name, image):
        path = self.base / name
        image.save(path)
        return {"path": name, "sha256": file_hash(path)}

    def test_default_is_byte_identical_and_does_not_load_masks(self):
        result, report = background.apply(self.image, {"kind": "main"}, self.base)
        self.assertIs(result, self.image)
        self.assertEqual(background.dependencies({}, self.base), {})
        self.assertFalse(report["applied"])

    def test_only_reviewed_background_changes_white_product_and_shadow_untouched(self):
        before = self.image.tobytes()
        result, report = background.apply(self.image, self.job, self.base)
        self.assertEqual(self.image.tobytes(), before)
        self.assertEqual(result.getpixel((0, 0)), (255, 255, 255))
        self.assertEqual(result.getpixel((12, 12)), (254, 254, 254))
        self.assertEqual(result.getpixel((12, 24)), (254, 254, 254))
        self.assertTrue(report["protected_pixels_unchanged"])
        self.assertEqual(report["changed_pixels"], 32 * 32 - 12 * 18)

    def test_known_product_bbox_is_additionally_protected(self):
        self.job["output_product_bbox_norm"] = [0, 0, 0.2, 0.2]
        result, _ = background.apply(self.image, self.job, self.base)
        self.assertEqual(result.getpixel((2, 2)), (254, 254, 254))

    def test_nearwhite_island_and_nonwhite_area_are_not_touched(self):
        ImageDraw.Draw(self.image).rectangle((1, 1, 8, 6), fill=(230, 230, 230))
        ImageDraw.Draw(self.image).rectangle((3, 3, 5, 4), fill=(253, 253, 253))
        self.job["background_normalization"]["source_pixel_sha256"] = pixel_hash(self.image)
        result, _ = background.apply(self.image, self.job, self.base)
        self.assertEqual(result.getpixel((4, 3)), (253, 253, 253))
        self.assertEqual(result.getpixel((1, 1)), (230, 230, 230))
        self.assertEqual(result.getpixel((31, 31)), (255, 255, 255))

    def test_untrusted_changed_or_mismatched_masks_fail_closed(self):
        original = copy.deepcopy(self.job)
        cases = [lambda c: c.update(reviewed=False),
                 lambda c: c.update(protection_covers_product_and_shadow=False),
                 lambda c: c.update(source_pixel_sha256="0" * 64),
                 lambda c: c["background_mask"].update(sha256="0" * 64),
                 lambda c: c.update(near_white_min=249)]
        for change in cases:
            with self.subTest(change=change):
                self.job = copy.deepcopy(original)
                change(self.job["background_normalization"])
                before = self.image.tobytes()
                with self.assertRaises(background.BackgroundError):
                    background.apply(self.image, self.job, self.base)
                self.assertEqual(before, self.image.tobytes())
        for image in (Image.new("L", (16, 16), 255), Image.new("L", (32, 32), 128), Image.new("L", (32, 32), 255)):
            self.job = copy.deepcopy(original)
            self.job["background_normalization"]["background_mask"] = self.save_mask("bad.png", image)
            with self.assertRaises(background.BackgroundError):
                background.apply(self.image, self.job, self.base)

    def test_mask_change_changes_dependencies(self):
        before = background.dependencies(self.job, self.base)
        self.allowed.putpixel((0, 0), 0)
        self.job["background_normalization"]["background_mask"] = self.save_mask("allowed.png", self.allowed)
        self.assertNotEqual(before, background.dependencies(self.job, self.base))

    def test_background_mask_limits_changes_and_invalid_paths_are_rejected(self):
        self.allowed.putpixel((0, 0), 0)
        self.job["background_normalization"]["background_mask"] = self.save_mask("allowed.png", self.allowed)
        result, _ = background.apply(self.image, self.job, self.base)
        self.assertEqual(result.getpixel((0, 0)), (254, 254, 254))
        for path in ("../allowed.png", str(self.base / "allowed.png"), "missing.png"):
            self.job["background_normalization"]["background_mask"]["path"] = path
            with self.assertRaises(background.BackgroundError):
                background.dependencies(self.job, self.base)


if __name__ == "__main__":
    unittest.main()
