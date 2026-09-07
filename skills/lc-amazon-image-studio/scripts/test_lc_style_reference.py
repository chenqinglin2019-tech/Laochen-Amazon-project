"""Regression coverage for external-only Amazon design-reference selection."""
from __future__ import annotations

import copy
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import lc_style_reference as references


_CONCURRENT_PREPARE_WORKER = r'''
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.environ["STYLE_REFERENCE_SCRIPTS"])
import lc_style_reference as references

ready_path = Path(os.environ["STYLE_REFERENCE_READY"])
start_path = Path(os.environ["STYLE_REFERENCE_START"])
selection_path = Path(os.environ["STYLE_REFERENCE_SELECTION"])
index_path = Path(os.environ["STYLE_REFERENCE_INDEX"])
selection_log = Path(os.environ["STYLE_REFERENCE_SELECTION_LOG"])
context = json.loads(os.environ["STYLE_REFERENCE_CONTEXT"])

ready_path.write_text("ready", encoding="utf-8")
deadline = time.monotonic() + 10
while not start_path.exists():
    if time.monotonic() >= deadline:
        raise RuntimeError("timed out waiting for concurrent prepare start")
    time.sleep(0.005)

original_select = references.select_references

def delayed_select(*args, **kwargs):
    with selection_log.open("a", encoding="utf-8") as stream:
        stream.write(f"{os.getpid()}\\n")
        stream.flush()
    time.sleep(0.3)
    return original_select(*args, **kwargs)

references.select_references = delayed_select
selection = references.prepare_selection(context, selection_path, index_path=index_path)
print(json.dumps(selection, ensure_ascii=False, sort_keys=True))
'''


class StyleReferenceTests(unittest.TestCase):
    def setUp(self):
        self.index = json.loads((ROOT / "assets/layouts/style_reference_index.json").read_text(encoding="utf-8"))
        self.profiles = json.loads((ROOT / "assets/layouts/style_reference_profiles.json").read_text(encoding="utf-8"))

    def _write_selection_test_index(self, base: Path) -> Path:
        references_data = []
        for identifier, category in (
            ("home-board", "home_decor"),
            ("travel-board", "travel_gear"),
            ("tool-board", "power_tool"),
        ):
            asset = base / f"{identifier}.bin"
            asset.write_bytes(identifier.encode("utf-8"))
            references_data.append({
                "id": identifier,
                "external_path": str(asset),
                "sha256": references._sha256(asset),
                "source_mode": "external_reference_only",
                "sample_asset_copied": False,
                "visual_observation": f"Fixture board for {category}.",
                "product_category": [category],
                "image_intent": ["editorial_hero"],
                "composition": ["copy_top_right"],
                "lighting": ["low_key"],
            })
        index_path = base / "index.json"
        index_path.write_text(json.dumps({
            "schema_version": 1,
            "asset_policy": "external_path_and_hash_only",
            "references": references_data,
        }), encoding="utf-8")
        return index_path

    @staticmethod
    def _selection_context(product: str, category: str) -> dict[str, object]:
        return {
            "product": product,
            "category": category,
            "intents": "editorial_hero",
            "composition": "copy_top_right",
            "lighting": "low_key",
            "max_auxiliary": 0,
        }

    def test_index_has_twenty_external_hash_locked_boards(self):
        self.assertEqual([], references.validate_index(self.index))
        self.assertEqual(20, len(self.index["references"]))
        for item in self.index["references"]:
            self.assertTrue(Path(item["external_path"]).is_absolute())
            self.assertEqual("external_reference_only", item["source_mode"])
            self.assertFalse(item["sample_asset_copied"])
            self.assertEqual(64, len(item["sha256"]))
            self.assertTrue(item["visual_observation"])

    def test_external_sources_match_locked_hashes_when_user_samples_are_available(self):
        sample_root = Path(self.index["references"][0]["external_path"]).parent
        if not sample_root.is_dir():
            self.skipTest("external user sample directory is unavailable")
        self.assertEqual([], references.verify_external_sources(self.index))

    def test_curated_black_rabbit_profiles_select_design_not_lookalike(self):
        self.assertEqual([], references.validate_profiles(self.profiles))
        expected = {
            "black-rabbit-05-primary": "fy_05_taper_candles",
            "black-rabbit-10-scene-whitespace": "fy_10_floor_lamp",
            "black-rabbit-11-detail-auxiliary": "fy_11_car_organizer",
        }
        for profile_id, primary_id in expected.items():
            with self.subTest(profile_id=profile_id):
                profile = references._profile_by_id(self.profiles, profile_id)
                result = references.select_references(self.index, profile)
                self.assertEqual(primary_id, result["primary"]["id"])
                self.assertLessEqual(len(result["auxiliaries"]), 2)
                self.assertTrue(result["primary"]["reason"])

    def test_automatic_black_rabbit_context_never_uses_a_preset_profile(self):
        contexts = {
            "05": ({
                "product": "black sitting rabbit home decoration with black-and-white check bow",
                "category": "",
                "intents": "editorial visible detail",
                "composition": ["catalog_left_lifestyle_right", "copy_top_right"],
                "lighting": ["warm_interior", "low_key"],
            }, "fy_05_taper_candles"),
            "10": ({
                "product": "black sitting rabbit home decoration with black-and-white check bow",
                "category": "",
                "intents": "scene whitespace lifestyle hero",
                "composition": ["right_product_left_blank", "negative_space"],
                "lighting": ["warm_interior", "soft_studio"],
            }, "fy_10_floor_lamp"),
            "11": ({
                "product": "black sitting rabbit home decoration with black-and-white check bow",
                "category": "",
                "intents": "show visible detail with a callout",
                "composition": ["callout_circles", "detail_insets"],
                "lighting": ["low_key", "neutral_studio"],
            }, "fy_11_car_organizer"),
        }
        with tempfile.TemporaryDirectory() as directory:
            for slot, (context, expected) in contexts.items():
                with self.subTest(slot=slot):
                    result = references.prepare_selection(context, Path(directory) / f"{slot}.json", verify_files=True)
                    self.assertEqual("selected", result["selection_status"])
                    self.assertEqual("automatic_context", result["profile_id"])
                    self.assertEqual(expected, result["primary"]["id"])
                    self.assertEqual("product_keyword", result["inference"]["category"])
                    self.assertEqual("intents_keyword", result["inference"]["intents"])
                    self.assertEqual(expected, result["style_profile_hint"]["design_reference_id"])
                    self.assertEqual("layout_local_only", result["style_profile_hint"]["font_resolution"])
                    self.assertNotIn("profile_id", context)

    def test_automatic_context_routes_multiple_product_categories(self):
        contexts = {
            "tool": ({
                "product": "compact cordless chainsaw",
                "category": "",
                "intents": "action hero feature detail",
                "composition": ["product_kit_left_action_right", "callout_circles"],
                "lighting": ["outdoor_daylight", "dramatic_contrast"],
            }, "fy_08_mini_chainsaw"),
            "beauty": ({
                "product": "concealer cosmetic",
                "category": "",
                "intents": ["feature_detail", "benefit_communication"],
                "composition": ["catalog_left_lifestyle_right", "close_up_detail"],
                "lighting": ["warm_interior", "soft_studio"],
            }, "fy_04_concealer"),
            "travel": ({
                "product": "hard shell suitcase",
                "category": "",
                "intents": ["lifestyle_hero", "feature_detail"],
                "composition": ["catalog_left_lifestyle_right", "copy_top_right"],
                "lighting": ["outdoor_daylight", "high_contrast"],
            }, "fy_02_suitcase"),
        }
        with tempfile.TemporaryDirectory() as directory:
            for category, (context, expected) in contexts.items():
                with self.subTest(category=category):
                    result = references.prepare_selection(context, Path(directory) / f"{category}.json", verify_files=True)
                    self.assertEqual(expected, result["primary"]["id"])

    def test_saved_selection_is_reused_without_automatic_overwrite(self):
        first_context = {
            "product": "black sitting rabbit home decoration",
            "category": "home_decor",
            "intents": "editorial_hero",
            "composition": "copy_top_right",
            "lighting": "low_key",
        }
        changed_context = {
            "product": "compact cordless chainsaw",
            "category": "power_tool",
            "intents": "action_hero",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "style_reference_selection.json"
            first = references.prepare_selection(first_context, path, verify_files=True)
            reused = references.prepare_selection(changed_context, path, verify_files=True)
            self.assertEqual(first, reused)
            self.assertEqual("fy_05_taper_candles", reused["primary"]["id"])

    def test_concurrent_first_prepare_commits_one_selection_and_reuses_it(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            index_path = self._write_selection_test_index(base)
            selection_path = base / "style_reference_selection.json"
            start_path = base / "start"
            selection_log = base / "selection.log"
            contexts = (
                self._selection_context("home decoration", "home_decor"),
                self._selection_context("travel suitcase", "travel_gear"),
            )
            ready_paths = [base / f"ready-{position}" for position in range(len(contexts))]
            processes: list[subprocess.Popen[str]] = []
            try:
                for context, ready_path in zip(contexts, ready_paths):
                    environment = os.environ.copy()
                    environment.update({
                        "STYLE_REFERENCE_SCRIPTS": str(ROOT / "scripts"),
                        "STYLE_REFERENCE_READY": str(ready_path),
                        "STYLE_REFERENCE_START": str(start_path),
                        "STYLE_REFERENCE_SELECTION": str(selection_path),
                        "STYLE_REFERENCE_INDEX": str(index_path),
                        "STYLE_REFERENCE_SELECTION_LOG": str(selection_log),
                        "STYLE_REFERENCE_CONTEXT": json.dumps(context),
                    })
                    processes.append(subprocess.Popen(
                        [sys.executable, "-c", _CONCURRENT_PREPARE_WORKER],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=environment,
                    ))

                deadline = time.monotonic() + 5
                while not all(path.exists() for path in ready_paths):
                    failed = next((process for process in processes if process.poll() is not None), None)
                    if failed is not None:
                        stdout, stderr = failed.communicate()
                        self.fail(f"concurrent prepare worker exited early: {stdout}\n{stderr}")
                    if time.monotonic() >= deadline:
                        self.fail("concurrent prepare workers did not become ready")
                    time.sleep(0.01)
                start_path.write_text("go", encoding="utf-8")

                results = []
                for process in processes:
                    stdout, stderr = process.communicate(timeout=10)
                    self.assertEqual(0, process.returncode, stderr)
                    results.append(json.loads(stdout))
            finally:
                for process in processes:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=3)

            self.assertEqual(results[0], results[1])
            self.assertEqual(results[0], json.loads(selection_path.read_text(encoding="utf-8")))
            self.assertEqual(1, len(selection_log.read_text(encoding="utf-8").splitlines()))

    def test_prepare_cli_uses_the_same_automatic_api(self):
        context = {
            "product": "hard shell suitcase",
            "category": "",
            "intents": "travel lifestyle hero feature detail",
            "composition": ["catalog_left_lifestyle_right", "copy_top_right"],
            "lighting": ["outdoor_daylight", "high_contrast"],
        }
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            context_path = base / "context.json"
            output_path = base / "selection.json"
            context_path.write_text(json.dumps(context), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                code = references.main([
                    "prepare", "--product-context", str(context_path),
                    "--selection-output", str(output_path),
                ])
            self.assertEqual(0, code)
            saved = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual("fy_02_suitcase", saved["primary"]["id"])

    def test_cli_selection_is_reused_by_the_python_api(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            index_path = self._write_selection_test_index(base)
            selection_path = base / "style_reference_selection.json"
            context_path = base / "context.json"
            cli_context = self._selection_context("home decoration", "home_decor")
            context_path.write_text(json.dumps(cli_context), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable, str(ROOT / "scripts" / "lc_style_reference.py"),
                    "--index", str(index_path),
                    "prepare", "--product-context", str(context_path),
                    "--selection-output", str(selection_path),
                ],
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            cli_selection = json.loads(completed.stdout)
            saved_bytes = selection_path.read_bytes()

            reused = references.prepare_selection(
                self._selection_context("power tool", "power_tool"),
                selection_path, index_path=index_path,
            )

            self.assertEqual(cli_selection, reused)
            self.assertEqual(saved_bytes, selection_path.read_bytes())
            self.assertEqual("home-board", reused["primary"]["id"])

    def test_unknown_context_is_explicitly_needs_input(self):
        with tempfile.TemporaryDirectory() as directory:
            result = references.prepare_selection(
                {"product": "unclassified object", "category": "", "intents": ""},
                Path(directory) / "style_reference_selection.json",
            )
            self.assertEqual("needs_input", result["selection_status"])
            self.assertIsNone(result["primary"])
            self.assertIn("STYLE_CONTEXT_INSUFFICIENT", result["needs_input"])
            self.assertEqual("unknown", result["inference"]["category"])

    def test_missing_selected_source_is_needs_input_not_a_pipeline_error(self):
        index = copy.deepcopy(self.index)
        for reference in index["references"]:
            if reference["id"] == "fy_05_taper_candles":
                reference["external_path"] = "/definitely-missing/style-board.jpeg"
        context = {
            "product": "black sitting rabbit home decoration",
            "category": "home_decor",
            "intents": "editorial_hero",
            "composition": "copy_top_right",
            "lighting": "low_key",
        }
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            index_path = base / "index.json"
            index_path.write_text(json.dumps(index), encoding="utf-8")
            result = references.prepare_selection(context, base / "selection.json", index_path=index_path)
            self.assertEqual("needs_input", result["selection_status"])
            self.assertIn("REFERENCE_SOURCE_MISSING:fy_05_taper_candles", result["needs_input"])

    def test_contextual_fit_beats_a_category_only_lookalike(self):
        template = copy.deepcopy(self.index["references"][0])
        lookalike = copy.deepcopy(template)
        lookalike.update(
            id="lookalike",
            product_category=["home_decor"], image_intent=["unrelated"],
            composition=["unrelated"], lighting=["unrelated"],
        )
        contextual = copy.deepcopy(template)
        contextual.update(
            id="contextual",
            product_category=["other_category"], image_intent=["editorial_hero"],
            composition=["copy_top_right"], lighting=["low_key"],
        )
        index = {
            "schema_version": 1,
            "asset_policy": "external_path_and_hash_only",
            "references": [lookalike, contextual],
        }
        profile = {
            "id": "test",
            "signals": {
                "product_category": ["home_decor"],
                "image_intent": ["editorial_hero"],
                "composition": ["copy_top_right"],
                "lighting": ["low_key"],
            },
            "max_auxiliary": 0,
            "minimum_score": 1,
            "minimum_matched_dimensions": 1,
        }
        result = references.select_references(index, profile)
        self.assertEqual("contextual", result["primary"]["id"])

    def test_locked_serif_assets_and_license_manifest(self):
        manifest_path = ROOT / "assets/fonts/manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries = {entry["file"]: entry for entry in manifest["fonts"]}
        for filename, weight in (("NotoSerif-Regular.ttf", 400), ("NotoSerif-SemiBold.ttf", 600)):
            with self.subTest(filename=filename):
                entry = entries[filename]
                path = ROOT / "assets/fonts" / filename
                self.assertTrue(path.is_file())
                self.assertEqual(weight, entry["weight"])
                self.assertEqual(entry["sha256"], references._sha256(path))
                self.assertEqual("OFL-NotoSerif.txt", entry["license_file"])
        self.assertTrue((ROOT / "assets/fonts/OFL-NotoSerif.txt").is_file())


if __name__ == "__main__":
    unittest.main()
