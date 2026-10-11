"""Synthetic main processing and historical recovery; no production auth or model calls."""
import copy
import unittest

from PIL import Image, ImageDraw

from test_lc_one_pass import OnePassTests
from lc_one_pass_design import compile_design
from lc_one_pass_export import alpha_background, export_settings, verify_export
from lc_one_pass_io import StudioError, digest, read_json, sha256, write_json
from lc_one_pass_main import clean_detached_residue, prepare_pixels, verify_prepared


class MainProcessingTests(unittest.TestCase):
    setUp = OnePassTests.setUp
    cli = OnePassTests.cli
    reservations = OnePassTests.reservations

    def project(self, **kwargs):
        return OnePassTests.project(self, modern=True, **kwargs)

    def ingest_main(self, path, source=None):
        item = self.reservations(path, job="01_main")[0]
        result = self.cli("ingest-batch", "--manifest", path, "--item", item["job"], item["attempt_id"], source or self.main)
        return item, result["results"][0]

    def approve(self, path, item, processing_id):
        return self.cli("main-background-check", "--manifest", path, "--job", "01_main",
                        "--attempt-id", item["attempt_id"], "--processing-id", processing_id,
                        "--verdict", "pass", "--observation", "Compared original and prepared: all components, holes and translucent edges retained.")

    def test_cleanup_protects_holes_lines_small_parts_and_near_edge_transition(self):
        image = Image.new("RGBA", (400, 400), (30, 20, 10, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((100, 80, 280, 300), fill=(255, 255, 255, 255))
        draw.rectangle((150, 140, 220, 220), fill=(0, 0, 0, 0))
        draw.point((180, 180), fill=(20, 20, 20, 8))  # Enclosed hole: keep.
        draw.line((280, 180, 345, 180), fill=(40, 70, 90, 120), width=1)
        draw.rectangle((310, 310, 312, 312), fill=(30, 20, 10, 255))  # Separate tiny component: keep.
        draw.point((98, 90), fill=(30, 20, 10, 8))  # Protected near edge: keep.
        draw.point((0, 5), fill=(20, 20, 20, 4))  # External weak residue: remove.
        before = image.getchannel("A")
        after, removed, limited = clean_detached_residue(before)
        self.assertEqual(removed, 1)
        self.assertFalse(limited)
        self.assertEqual(after.getpixel((0, 5)), 0)
        for point in ((180, 180), (98, 90), (330, 180), (311, 311), (120, 120)):
            self.assertEqual(after.getpixel(point), before.getpixel(point))
        for kind in ("unknown", "translucent"):
            _, result = prepare_pixels(image, (1600, 1600), kind)
            self.assertEqual(result["removed_pixels"], 0)
            self.assertEqual(result["source_bbox"][0], 0)

    def test_cleanup_total_limit_keeps_all_candidates(self):
        alpha = Image.new("L", (200, 200), 0)
        ImageDraw.Draw(alpha).rectangle((80, 80, 120, 120), fill=255)
        for x in range(2, 128, 4):
            alpha.putpixel((x, 4), 1)
        result, removed, limited = clean_detached_residue(alpha)
        self.assertTrue(limited)
        self.assertEqual(removed, 0)
        self.assertEqual(result.tobytes(), alpha.tobytes())

    def test_connected_weak_border_is_preserved_and_recentered(self):
        image = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((80, 100, 120, 194), fill=(200, 70, 40, 255))
        draw.line((100, 195, 100, 199), fill=(200, 70, 40, 14), width=1)
        result, info = prepare_pixels(image, (1600, 1600), "opaque")
        self.assertTrue(info["requires_endpoint_check"])
        self.assertEqual(info["removed_pixels"], 0)
        self.assertEqual(info["source_bbox"], [80, 100, 121, 200])
        self.assertEqual(info["fitted_size"], [590, 1440])
        self.assertIsNotNone(alpha_background(result))
        self.assertEqual(result.getchannel("A").crop((0, 0, 1600, 50)).getbbox(), None)

    def test_invalid_background_and_real_clipping_are_rejected(self):
        invalid = [Image.new("RGB", (100, 100), "white"),
                   Image.new("RGBA", (100, 100), (255, 255, 255, 0)),
                   Image.new("RGBA", (100, 100), (254, 254, 254, 255))]
        image = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
        ImageDraw.Draw(image).rectangle((0, 30, 60, 80), fill=(255, 255, 255, 255))
        invalid.append(image)
        for image in invalid:
            with self.subTest(mode=image.mode), self.assertRaises(StudioError):
                prepare_pixels(image, (1600, 1600), "opaque")

    def test_transparent_hidden_rgb_does_not_add_dark_edges(self):
        image = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
        ImageDraw.Draw(image).rectangle((30, 30, 70, 70), fill=(255, 255, 255, 128))
        prepared, _ = prepare_pixels(image, (1600, 1600), "translucent")
        final = Image.alpha_composite(Image.new("RGBA", prepared.size, "white"), prepared).convert("RGB")
        self.assertEqual(final.getextrema(), ((255, 255),) * 3)

    def test_new_ingest_processing_id_and_exact_white_delivery(self):
        path = self.project(count=1)
        item, result = self.ingest_main(path)
        self.assertEqual(result["status"], "main_background_pending")
        self.assertNotEqual(result["path"], result["raw_path"])
        before = path.read_bytes()
        for processing_id in (None, "stale"):
            args = ["main-background-check", "--manifest", path, "--job", "01_main", "--attempt-id", item["attempt_id"],
                    "--verdict", "pass", "--observation", "Synthetic"]
            if processing_id:
                args += ["--processing-id", processing_id]
            self.cli(*args, code=2)
            self.assertEqual(path.read_bytes(), before)
        self.approve(path, item, result["processing_id"])
        delivered = self.cli("deliver", "--manifest", path)
        self.assertTrue(delivered["complete"])
        job = read_json(path)["jobs"][0]
        with Image.open(delivered["images"][0]["path"]) as final, Image.open(path.parent / job["delivery"]["white_background"]["mask"]) as mask:
            self.assertEqual(final.mode, "RGB")
            self.assertEqual(final.size, (1600, 1600))
            self.assertEqual(Image.composite(final, Image.new("RGB", final.size, "white"), mask).getextrema(), ((255, 255),) * 3)
        before = path.read_bytes()
        self.cli("prepare-main", "--manifest", path, "--job", "01_main")
        self.assertEqual(path.read_bytes(), before)
        self.cli("status", "--manifest", path)
        self.cli("deliver", "--manifest", path)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(self.reservations(path))

    def test_local_type_change_requires_new_check_without_generation(self):
        path = self.project(count=1)
        item, result = self.ingest_main(path)
        self.approve(path, item, result["processing_id"])
        before = read_json(path)["jobs"][0]
        patch = self.root / "local-settings.json"
        write_json(patch, {"jobs": [{"id": "01_main", "main_foreground_type": "opaque"}]})
        self.cli("configure", "--manifest", path, "--input", patch)
        self.cli("plan", "--manifest", path)
        self.assertFalse(self.reservations(path))
        prepared = self.cli("prepare-main", "--manifest", path, "--job", "01_main")
        self.assertNotEqual(prepared["processing_id"], result["processing_id"])
        after = read_json(path)["jobs"][0]
        self.assertEqual(after["generation_fingerprint"], before["generation_fingerprint"])
        self.assertEqual(after["generation_attempts"], before["generation_attempts"])
        self.assertNotIn("main_background_check", after)
        self.assertFalse(self.cli("deliver", "--manifest", path)["complete"])

    def test_preparation_refuses_unknown_or_stale_source(self):
        path = self.project(count=1)
        item = self.reservations(path)[0]
        self.cli("ingest-batch", "--manifest", path, "--unknown", item["job"], item["attempt_id"], "Unknown submission")
        before = path.read_bytes()
        self.cli("prepare-main", "--manifest", path, "--job", "01_main", code=2)
        self.assertEqual(path.read_bytes(), before)
        self.cli("recover-attempt", "--manifest", path, "--job", item["job"], "--attempt-id", item["attempt_id"], "--reason", "Existing file found")
        self.cli("ingest-batch", "--manifest", path, "--item", item["job"], item["attempt_id"], self.main)
        inputs = self.root / "change-product.json"
        write_json(inputs, {"jobs": [{"id": "01_main", "design_brief": {"goal": "Different product", "scene": "Studio", "composition": "Centered"}}]})
        self.cli("configure", "--manifest", path, "--input", inputs)
        self.cli("plan", "--manifest", path)
        self.cli("prepare-main", "--manifest", path, "--job", "01_main", code=2)

    def test_legacy_recovery_preserves_budget_prompt_and_secondary(self):
        path = OnePassTests.project(self, modern=False)
        initial = self.reservations(path)
        for item in initial:
            self.cli("ingest-batch", "--manifest", path, "--item", item["job"], item["attempt_id"], self.secondary)
        repair = self.reservations(path)[0]
        image = Image.open(self.main).convert("RGBA")
        image.putpixel((0, 5), (0, 0, 0, 4))
        raw = self.root / "weak-border.png"
        image.save(raw)
        # Reproduce the former one-repair policy in an isolated project.
        from unittest.mock import patch
        with patch("lc_one_pass.MAIN_BACKGROUND_REPAIR_LIMIT", 1):
            self.cli("ingest-batch", "--manifest", path, "--item", repair["job"], repair["attempt_id"], raw)
        before = read_json(path)
        self.assertEqual(before["jobs"][0]["status"], "blocked")
        secondary_hash = sha256(path.parent / before["jobs"][1]["delivery"]["path"])
        result = self.cli("prepare-main", "--manifest", path, "--job", "01_main")
        self.assertEqual(result["status"], "main_background_pending")
        after = read_json(path)
        for key in ("generation_fingerprint", "prompt_hash", "generation_attempts", "background_repairs"):
            self.assertEqual(after["jobs"][0][key], before["jobs"][0][key])
        self.assertEqual(after["jobs"][0]["background_repairs"], 1)
        self.assertEqual(after["jobs"][1], before["jobs"][1])
        self.assertEqual(sha256(path.parent / after["jobs"][1]["delivery"]["path"]), secondary_hash)
        self.approve(path, repair, result["processing_id"])
        self.assertTrue(self.cli("deliver", "--manifest", path)["complete"])

    def test_new_prompt_is_versioned_and_legacy_export_settings_unchanged(self):
        path = self.project()
        manifest = read_json(path)
        main, secondary = manifest["jobs"]
        modern = compile_design(manifest, main, path.parent)["prompt"]
        self.assertIn("90 percent", modern)
        main.pop("main_prompt_version")
        legacy = compile_design(manifest, main, path.parent)["prompt"]
        self.assertNotIn("90 percent", legacy)
        main["main_foreground_type"] = "opaque"
        self.assertEqual(compile_design(manifest, main, path.parent)["prompt"], legacy)
        expected = {"canvas": secondary["canvas"], "human_source": "none", "keywords": [], "format": "PNG", "version": 1}
        self.assertEqual(export_settings(secondary), expected)

    def test_prepared_raw_parameters_mask_and_final_tampering_are_detected(self):
        path = self.project(count=1)
        item, result = self.ingest_main(path)
        self.approve(path, item, result["processing_id"])
        original = read_json(path)
        job = original["jobs"][0]
        for field in ("raw_output",):
            artifact = path.parent / job[field]
            data = artifact.read_bytes()
            artifact.write_bytes(b"tampered")
            self.assertFalse(self.cli("deliver", "--manifest", path)["complete"])
            artifact.write_bytes(data)
        for relative in (job["main_processing"]["path"], job["delivery"]["path"], job["delivery"]["white_background"]["mask"]):
            artifact = path.parent / relative
            data = artifact.read_bytes()
            artifact.write_bytes(b"tampered")
            self.assertFalse(self.cli("deliver", "--manifest", path)["complete"])
            artifact.write_bytes(data)
        changed = copy.deepcopy(original)
        changed["jobs"][0]["main_processing"]["settings"]["parameters"]["weak_alpha_max"] = 255
        write_json(path, changed)
        self.assertFalse(self.cli("deliver", "--manifest", path)["complete"])
        write_json(path, original)
        changed = copy.deepcopy(original)
        changed["jobs"][0]["main_background_check"]["processing_id"] = "old"
        write_json(path, changed)
        self.assertFalse(self.cli("deliver", "--manifest", path)["complete"])
        write_json(path, original)
        self.assertTrue(self.cli("deliver", "--manifest", path)["complete"])


if __name__ == "__main__":
    unittest.main()
