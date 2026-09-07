"""V3 recipes and renderer regressions; fixtures are local synthetic test images."""
from __future__ import annotations

import base64
import copy
import io
import os
from pathlib import Path
import tempfile
import unittest

from PIL import Image, PngImagePlugin

import lc_layout as layout
from lc_layout_v3 import RECIPES, mapped_product_box, panel_placement


class LayoutV3Tests(unittest.TestCase):
    def job(self, recipe="header_footer", canvas=None):
        return {"id": "v3", "kind": "listing", "canvas": canvas or [1000, 1000], "layout_input": "base.png",
                "layout": {"version": 3, "recipe": recipe, "theme": "warm", "text_groups": [
                    {"id": "title", "box": [.07, .07, .86, .18], "headline": "Easter Display", "body": "Indoor table decor",
                     "headline_family": "sans", "headline_weight": 700, "text_color": "#FFFFFF",
                     "surface": {"kind": "solid", "color": "#101010", "opacity": 1}},
                    {"id": "footer", "box": [.07, .79, .86, .15], "headline": "A checked bow", "headline_family": "serif", "headline_weight": 400,
                     "text_color": "#111111", "surface": {"kind": "solid", "color": "#FFFFFF", "opacity": 1}}],
                           "panels": [{"id": "scene", "image": "scene.png", "box": [.07, .35, .86, .38], "fit": "contain", "evidence_refs": ["source-1"], "product_bbox_norm": [.4, .2, .2, .6]}]}}

    def test_six_recipe_geometries_and_group_ink(self):
        self.assertEqual(len(RECIPES), 6)
        for recipe in RECIPES:
            for canvas in ([2000, 2000], [2000, 2600], [1464, 600]):
                job = self.job(recipe, canvas)
                layout.validate_layout_v3(job["layout"])
                result = layout.layout_geometry(job)
                self.assertEqual(result["recipe"], recipe)
                self.assertEqual(len(result["text_groups"]), 2)
                self.assertEqual(len(result["panels"]), 1)
                self.assertEqual(result["text_regions_norm"][0], [.07, .07, .86, .18])

    def test_invalid_inputs_fail_without_rendering(self):
        cases = []
        invalid = self.job();invalid["layout"]["panels"] *= 5;cases.append(invalid)
        invalid = self.job();invalid["layout"]["text_groups"] *= 4;cases.append(invalid)
        invalid = self.job();invalid["layout"]["text_groups"][0]["text_color"] = "red";cases.append(invalid)
        invalid = self.job();invalid["layout"]["text_groups"][0]["mobile_sizes"] = {"headline": 17};cases.append(invalid)
        invalid = self.job();invalid["layout"]["panels"][0]["evidence_refs"] = [];cases.append(invalid)
        invalid = self.job();invalid["layout"]["panels"][0]["source_crop"] = [0, 0, 2, 1];cases.append(invalid)
        invalid = self.job();invalid["layout"]["text_groups"][0]["surface"]["opacity"] = float("nan");cases.append(invalid)
        invalid = self.job();invalid["layout"]["faq"] = [{"question": "Where?", "answer": "Inside"}];cases.append(invalid)
        invalid = self.job();invalid["layout"]["headline"] = "Duplicated source";cases.append(invalid)
        invalid = self.job();invalid["layout"].update(canvas_background="#FFFFFF", panels=[]);cases.append(invalid)
        invalid = self.job();invalid["layout"]["canvas_background"] = "#FFFFFF";invalid["layout"].pop("panels");cases.append(invalid)
        invalid = self.job();invalid["layout"]["text_groups"][0]["headline_treatment"] = {"kind": "outline", "color": "blue"};cases.append(invalid)
        invalid = self.job();invalid["layout"]["text_groups"][0]["headline_treatment"] = {"kind": "shadow", "color": "#111111", "offset_em": [.8, 0]};cases.append(invalid)
        for job in cases:
            with self.subTest(job=job), self.assertRaises(layout.LayoutError):
                layout.validate_layout_v3(job["layout"])

    def test_headline_treatments_are_prepared_without_changing_text_color_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            Image.new("RGB", (1000, 1000), "white").save(base / "base.png")
            Image.new("RGB", (200, 100), "#DDCCAA").save(base / "scene.png")
            job = self.job()
            title = job["layout"]["text_groups"][0]
            title["headline_treatment"] = {"kind": "outline", "color": "#111111", "width_em": .06}
            prepared = layout._prepare_job({}, base, job)
            self.assertEqual(prepared["text_groups"][0]["headline_treatment"], title["headline_treatment"])
            title["headline_treatment"] = {"kind": "shadow", "color": "#111111", "offset_em": [.06, .08], "blur_em": .08, "opacity": .55}
            self.assertEqual(layout._prepare_job({}, base, job)["text_groups"][0]["headline_treatment"]["kind"], "shadow")

    def test_measurement_render_has_no_review_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            Image.new("RGB", (1000, 1000), "white").save(base / "base.png")
            Image.new("RGB", (200, 100), "#DDCCAA").save(base / "scene.png")
            rendered = layout.render_batch({}, base, [self.job()], measure_only=True)["v3"]
            self.assertTrue(rendered["passed"], rendered["checks"])
            self.assertIsNone(rendered["output_path"])
            self.assertTrue(rendered["runtime"]["measurement_only"])
            self.assertFalse((base / "review").exists())

    def test_brief_defaults_reach_geometry_and_renderer_with_explicit_precedence(self):
        job = {"id": "brief", "kind": "listing", "canvas": [1464, 600], "layout_input": "base.png",
               "design_brief": {"layout": {"recipe": "photo_overlay", "headline_family": "serif", "headline_weight": 400,
                                           "text_color": "#FFFFFF", "align": "right", "text_group_box": [.07, .15, .40, .70],
                                           "text_surface": {"kind": "solid", "color": "#111111", "opacity": 1}}},
               "layout": {"version": 3, "text_groups": [{"id": "title", "headline": "Easter", "headline_family": "sans", "headline_weight": 700}]}}
        untouched = copy.deepcopy(job)
        resolved = layout.resolve_layout_defaults(job)
        layout.validate_layout_v3(resolved)
        self.assertEqual(resolved["recipe"], "photo_overlay")
        self.assertEqual(resolved["text_groups"][0]["headline_family"], "sans")
        self.assertEqual(resolved["text_groups"][0]["headline_weight"], 700)
        self.assertEqual(resolved["text_groups"][0]["text_color"], "#FFFFFF")
        self.assertEqual(layout.layout_geometry(job)["text_groups"][0]["box"], [.07, .15, .40, .70])
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp);Image.new("RGB", (1464, 600), "white").save(base / "base.png")
            prepared = layout._prepare_job({}, base, job)
            self.assertEqual(prepared["text_groups"][0]["align"], "right")
            self.assertEqual(prepared["text_groups"][0]["surface"]["kind"], "solid")
        self.assertEqual(job, untouched)
        changed = copy.deepcopy(job);changed["design_brief"]["layout"]["text_color"] = "#EEEEEE"
        self.assertNotEqual(layout.layout_fingerprint({}, job), layout.layout_fingerprint({}, changed))
        changed = copy.deepcopy(job);changed["design_brief"]["layout"]["headline_family"] = "sans"
        self.assertEqual(layout.resolve_layout_defaults(job)["text_groups"], layout.resolve_layout_defaults(changed)["text_groups"])
        legacy = {"layout": {"version": 2, "headline": "Existing"}, "design_brief": job["design_brief"]}
        self.assertEqual(layout.resolve_layout_defaults(legacy), legacy["layout"])

    def test_wide_grid_is_recomposed_not_scaled_square(self):
        job = self.job("scene_grid", [1464, 600])
        job["layout"]["text_groups"] = [{"id": "main", "headline": "Indoor Scenes"}]
        job["layout"]["panels"] = [{"id": str(i), "image": "scene.png", "evidence_refs": ["source"]} for i in range(4)]
        wide = layout.layout_geometry(job)
        job["canvas"] = [2000, 2000]
        square = layout.layout_geometry(job)
        self.assertLess(wide["text_groups"][0]["box"][2], square["text_groups"][0]["box"][2])
        self.assertGreater(wide["panels"][0]["box"][0], wide["text_groups"][0]["box"][0] + wide["text_groups"][0]["box"][2])

    def test_v2_icon_number_and_dimension_arrow_reachable(self):
        for template, item, expected in (("benefits", {"text": "Visible bow", "icon": "check"}, "icon"),
                                         ("components", {"text": "Place"}, "number")):
            job = {"kind": "listing", "canvas": [2000, 2000], "layout": {"version": 2, "template": template, "items": [item]}}
            self.assertIn(expected, layout.layout_geometry(job)["items"][0])
        job["layout"] = {"version": 2, "template": "dimensions", "items": [{"text": "35 cm", "axis": "vertical", "dimension_points": [[.7, .2], [.7, .75]], "evidence_refs": ["measured"]}]}
        self.assertEqual(layout.layout_geometry(job)["lines"][0]["points"], [[.7, .2], [.7, .75]])
        self.assertTrue(layout.layout_geometry(job)["lines"][0]["arrow"])

    def test_panel_crop_protection_mapping(self):
        panel = {"box": [.25, .25, .5, .5], "source_size": [200, 100], "source_crop": [0, 0, 1, 1], "fit": "cover", "product_bbox_norm": [.4, .2, .2, .6]}
        panel["placement"] = panel_placement(panel, [1000, 1000])
        self.assertEqual(panel["placement"]["source"], [50, 0, 100, 100])
        for actual, expected in zip(mapped_product_box(panel, [1000, 1000]), [.4, .35, .2, .3]):
            self.assertAlmostEqual(actual, expected)
        panel["fit"] = "contain";panel["placement"] = panel_placement(panel, [1000, 1000])
        self.assertEqual(panel["placement"]["destination"], [250, 375, 500, 250])
        for actual, expected in zip(mapped_product_box(panel, [1000, 1000]), [.45, .425, .1, .15]):
            self.assertAlmostEqual(actual, expected)

    def test_minimal_font_set_preserves_coverage(self):
        fonts, missing = layout._font_payload(["Easter Display", "Indoor table decor"], version=3, headline_family="serif", subset=True)
        self.assertEqual(missing, [])
        self.assertLess(sum(len(face["uri"]) for face in fonts), 5_000_000)
        self.assertFalse(any(face["family"] in {"CJK", "Arabic"} for face in fonts))
        fonts, missing = layout._font_payload(["春季 Easter مرحبا"], version=3, headline_family="serif", subset=True)
        self.assertEqual(missing, [])
        self.assertTrue({"CJK", "Arabic"} <= {face["family"] for face in fonts})
        # A zh/ja/ko job still prefers the CJK font for Latin glyphs. Dropping it
        # solely because Latin covers those characters would change old pixels.
        fonts, missing = layout._font_payload(["Indoor Decor"], version=2, headline_family="sans", subset=True, weights=(400,), primary_families=("CJK",))
        self.assertEqual(missing, [])
        self.assertIn("CJK", {face["family"] for face in fonts})
        self.assertEqual({face["weight"] for face in fonts}, {400})

    def test_png_passthrough_pixels_and_content_invalidation(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "input.png"
            original = Image.new("RGBA", (40, 30), (21, 80, 32, 126));original.save(path)
            uri = layout._raster_uri(path)
            self.assertEqual(base64.b64decode(uri.split(",", 1)[1]), path.read_bytes())
            with Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1]))) as decoded:
                self.assertEqual(original.tobytes(), decoded.tobytes())
            Image.new("RGBA", (40, 30), (42, 80, 32, 126)).save(path)
            self.assertNotEqual(uri, layout._raster_uri(path))
            metadata = PngImagePlugin.PngInfo();metadata.add(b"gAMA", b"\x00\x00\xb1\x8f")
            original.save(path, pnginfo=metadata)
            normalized = base64.b64decode(layout._raster_uri(path).split(",", 1)[1])
            self.assertNotEqual(normalized, path.read_bytes())
            with Image.open(io.BytesIO(normalized)) as decoded:
                self.assertEqual(original.tobytes(), decoded.tobytes())

    def test_prepared_groups_and_panel_hashes(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            Image.new("RGB", (1000, 1000), "white").save(base / "base.png")
            Image.new("RGB", (200, 100), "#DDCCAA").save(base / "scene.png")
            job = self.job()
            prepared = layout._prepare_job({}, base, job)
            self.assertEqual(prepared["text_groups"][0]["ink"], "#FFFFFF")
            self.assertEqual(prepared["text_groups"][1]["ink"], "#111111")
            self.assertIn("A checked bow", layout._prepared_texts(prepared))
            self.assertTrue(any(region.get("panel") == "scene" for region in prepared["protected"]))
            replaced = copy.deepcopy(job)
            replaced["output_product_bbox_norm"] = [.05, .05, .9, .9]
            replaced["layout"]["canvas_background"] = "#FFFFFF"
            replaced_prepared = layout._prepare_job({}, base, replaced)
            self.assertEqual(len(replaced_prepared["protected"]), 1)
            self.assertEqual(replaced_prepared["protected"][0]["panel"], "scene")
            replaced["layout"].pop("canvas_background")
            self.assertEqual(len(layout._prepare_job({}, base, replaced)["protected"]), 2)
            before = layout.layout_fingerprint({}, job, base)
            Image.new("RGB", (200, 100), "#AACCDD").save(base / "scene.png")
            self.assertNotEqual(before, layout.layout_fingerprint({}, job, base))
            bad = copy.deepcopy(job);bad["layout"]["panels"][0]["image"] = "/tmp/outside.png"
            with self.assertRaises(layout.LayoutError):
                layout._prepare_job({}, base, bad)

    @unittest.skipUnless(os.environ.get("LC_LAYOUT_BROWSER_TEST") == "1", "opt-in Chromium regression")
    def test_browser_multigroup_grid_safety_and_shared_batch_metrics(self):
        with tempfile.TemporaryDirectory(prefix="布局V3-") as temp:
            base = Path(temp)
            Image.new("RGB", (1000, 1000), "#EEEEEE").save(base / "base.png")
            Image.new("RGB", (200, 100), "#DDD2BC").save(base / "scene.png")
            job = self.job()
            grid = self.job("scene_grid");grid["id"] = "grid"
            grid["output_product_bbox_norm"] = [.05, .05, .9, .9]
            grid["layout"]["canvas_background"] = "#FFFFFF"
            grid["layout"]["text_groups"] = [{"id": "title", "headline": "Indoor Scenes", "headline_weight": 700, "text_color": "#111111"}]
            grid["layout"]["panels"] = [{"id": f"scene-{i}", "image": "scene.png", "evidence_refs": ["source"], "product_bbox_norm": [.4, .2, .2, .6]} for i in range(4)]
            protected = copy.deepcopy(job);protected["id"] = "protected";protected["layout"]["text_groups"][0]["box"] = [.30, .48, .4, .2]
            overlap = copy.deepcopy(grid);overlap["id"] = "overlap";overlap["layout"]["panels"][1]["box"] = [.03, .25, .455, .335]
            steps = copy.deepcopy(grid);steps["id"] = "steps";steps["layout"]["recipe"] = "steps";steps["layout"]["panels"] = steps["layout"]["panels"][:3]
            output = layout.render_batch({}, base, [job, grid, protected, overlap, steps])
            self.assertTrue(output["v3"]["passed"], output["v3"]["checks"])
            self.assertTrue(output["grid"]["passed"], output["grid"]["checks"])
            self.assertTrue(output["steps"]["passed"], output["steps"]["checks"])
            self.assertEqual(len([box for box in output["steps"]["bboxes"] if box["id"].startswith("panel-step-")]), 3)
            self.assertFalse(output["protected"]["passed"])
            self.assertFalse(output["overlap"]["passed"])
            self.assertTrue(any(check["check"] == "panel_collision" and not check["passed"] for check in output["overlap"]["checks"]))
            self.assertTrue(any(check["check"] == "protected_region" and not check["passed"] for check in output["protected"]["checks"]))
            self.assertEqual(len([box for box in output["grid"]["bboxes"] if box["kind"] == "panel"]), 4)
            with Image.open(base / output["grid"]["output_path"]) as rendered:
                self.assertEqual(rendered.convert("RGB").getpixel((2, 2)), (255, 255, 255))
            owners = [result for result in output.values() if result["runtime"].get("batch_metrics")]
            self.assertEqual(len(owners), 1)
            self.assertEqual(owners[0]["runtime"]["batch_metrics"]["browser_launches"], 1)
            self.assertLess(owners[0]["runtime"]["batch_metrics"]["font_payload_bytes"], 5_000_000)
            self.assertTrue(all("preview_seconds" in result["runtime"] for result in output.values()))

    @unittest.skipUnless(os.environ.get("LC_LAYOUT_BROWSER_TEST") == "1", "opt-in Chromium regression")
    def test_background_without_panels_cannot_hide_base_product_and_pass(self):
        with tempfile.TemporaryDirectory(prefix="V3-base-product-") as temp:
            base = Path(temp)
            image = Image.new("RGB", (1000, 1000), "white")
            image.paste("black", (400, 200, 600, 800));image.save(base / "base.png")
            valid = {"id": "visible", "kind": "listing", "canvas": [1000, 1000], "layout_input": "base.png",
                     "output_product_bbox_norm": [.4, .2, .2, .6],
                     "layout": {"version": 3, "recipe": "photo_overlay", "text_groups": [
                         {"id": "title", "box": [.07, .07, .8, .12], "headline": "Bunny", "text_color": "#111111"}]}}
            invalid = copy.deepcopy(valid);invalid["id"] = "hidden"
            invalid["layout"].update(canvas_background="#FFFFFF", panels=[])
            results = layout.render_batch({}, base, [invalid, valid])
            self.assertFalse(results["hidden"]["passed"])
            self.assertIsNone(results["hidden"]["output_path"])
            self.assertTrue(any(check["check"] == "input_validation" and "hide the base product" in check["detail"] for check in results["hidden"]["checks"]))
            self.assertFalse((base / "review/layouts/hidden.png").exists())
            self.assertTrue(results["visible"]["passed"], results["visible"]["checks"])
            with Image.open(base / results["visible"]["output_path"]) as rendered:
                self.assertEqual(rendered.convert("RGB").getpixel((500, 500)), (0, 0, 0))

    @unittest.skipUnless(os.environ.get("LC_LAYOUT_BROWSER_TEST") == "1", "opt-in Chromium regression")
    def test_browser_square_portrait_wide_gradients_languages_and_overflow(self):
        with tempfile.TemporaryDirectory(prefix="V3-多语言-") as temp:
            base = Path(temp);jobs = []
            for index, canvas in enumerate(([1000, 1000], [1000, 1300], [1464, 600])):
                source = f"base-{index}.png";Image.new("RGB", canvas, "#EFEFEF").save(base / source)
                for recipe in RECIPES:
                    job = {"id": f"{recipe}-{index}", "kind": "listing", "canvas": canvas, "layout_input": source,
                           "layout": {"version": 3, "recipe": recipe, "text_groups": [{"id": "title", "box": [.08, .13, .70, .75],
                           "headline": "Easter Display", "headline_weight": 700, "body": "Indoor scenes", "text_color": "#111111",
                           "surface": {"kind": "gradient", "color": "#FFFFFF", "opacity": .95, "direction": "vertical"}}]}}
                    jobs.append(job)
            for language, headline in (("zh", "春日室内陈列"), ("ar", "زينة داخلية")):
                job = copy.deepcopy(jobs[0]);job.update(id=language, language=language);job["layout"]["text_groups"][0]["headline"] = headline;jobs.append(job)
            overflow = copy.deepcopy(jobs[0]);overflow["id"] = "overflow";overflow["layout"]["text_groups"][0]["box"] = [.1, .1, .25, .15];jobs.append(overflow)
            results = layout.render_batch({}, base, jobs)
            for job in jobs[:-1]:
                self.assertTrue(results[job["id"]]["passed"], (job["id"], results[job["id"]]["checks"]))
            self.assertFalse(results["overflow"]["passed"])


if __name__ == "__main__":
    unittest.main()
