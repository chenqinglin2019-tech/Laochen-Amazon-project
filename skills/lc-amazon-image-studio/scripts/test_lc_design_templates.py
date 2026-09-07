"""Offline behavioral tests for portable reviewed design templates."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import lc_design_templates as templates
from lc_style_reference import _write_json


def fixture() -> dict:
    source = {"id": "sample_01", "filename": "案例_01.png", "sha256": "a" * 64,
              "region_norm": [0, 0, 1, 1], "observation": "A warm still life with a clear lateral reading area."}
    family = {"id": "warm-editorial", "revision": 1, "name": "Warm editorial", "categories": ["home_decor"],
              "keywords": ["warm", "wood", "cozy"], "description": "Restrained natural interiors and tactile product presence.",
              "style": {"palette": "Warm neutrals with a dark anchor.", "typography": "Serif display with simple sans supporting text.",
                        "photography": "Soft lateral daylight and authentic contact shadows.", "graphics": "Fine warm-gray dividers.",
                        "rhythm": "Alternate a full scene with tighter supporting details."},
              "avoid": ["Do not inherit sample-product facts."], "source_ids": [source["id"]],
              "review": {"visual_reviewed": True, "notes": "Source reviewed; no product-specific copy was retained."}}
    template = {"id": "warm-scene-sidebar", "revision": 1, "family_id": family["id"], "name": "Warm scene sidebar",
                "intents": ["lifestyle_hero", "gift_lifestyle"], "kinds": ["secondary", "a_plus"],
                "canvas_shapes": ["square", "portrait", "wide"], "recipe": "photo_sidebar",
                "description": "A large photographic product scene balanced by one narrow reading zone.",
                "generation": {"composition": "Product occupies the right half; leave the left side uncluttered.", "lighting": "Broad soft daylight."},
                "layout": {"recipe": "photo_sidebar", "headline_family": "serif", "headline_weight": 400,
                           "text_color": "#26221E", "align": "left", "text_group_box": [.05, .1, .35, .75],
                           "text_surface": {"kind": "transparent"}},
                "prompt_template": "Photograph {product} in {scene}; show {selling_job}. Preserve true geometry and reserve quiet space on the left.",
                "scene_default": "a naturally lit neutral interior", "fixed_style": ["Maintain a restrained visual hierarchy."],
                "adaptation_rules": ["Increase the reading area when approved copy needs it; do not reduce font size."],
                "avoid": ["Do not invent accessories or numerical claims."], "source_ids": [source["id"]],
                "review": {"visual_reviewed": True, "notes": "Reviewed layout without sample branding or copy."}}
    return {**templates.empty_library(), "sources": [source], "families": [family], "templates": [template]}


class TemplateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.builtin = self.base / "builtin.json"
        self.user = self.base / "user.json"
        self.library = fixture()
        _write_json(self.builtin, self.library)
        self.context = {"product": "Wood shelf decor", "category": "home_decor", "style_preferences": "warm wood"}
        self.job = {"kind": "listing", "canvas": [2000, 2000], "selling_job": "A welcoming lifestyle scene", "text_mode": "local_overlay", "layout": {"recipe": "photo_overlay", "headline": "Approved project copy"}}

    def tearDown(self):
        self.tmp.cleanup()

    def _import(self, payload):
        return templates.import_library(payload, self.user, self.builtin)

    def _variant(self, suffix="two"):
        payload = templates.empty_library()
        record = copy.deepcopy(self.library["templates"][0])
        record.update(id=f"warm-scene-{suffix}", name=f"Warm scene {suffix}")
        record["generation"]["composition"] += f" Use the distinct {suffix} arrangement."
        payload["templates"].append(record)
        return payload

    def _with_canvas_variants(self):
        library = copy.deepcopy(self.library)
        library["templates"][0]["layout"].update(
            product_region_norm=[.45, .1, .5, .8],
            canvas_variants={
                "square": {"text_group_box": [.05, .1, .35, .7], "product_region_norm": [.45, .1, .5, .8],
                           "composition_note": "Use the square side-by-side arrangement."},
                "portrait": {"text_group_box": [.06, .05, .88, .28], "product_region_norm": [.1, .39, .8, .55],
                             "composition_note": "Use the portrait top-reading composition instead of a narrow side rail."},
                "wide": {"text_group_box": [.05, .14, .42, .72], "product_region_norm": [.55, .05, .4, .9],
                         "composition_note": "Use a broad left reading zone and a right photographic subject."}})
        return library

    def test_valid_library_empty_user_and_source_filename(self):
        self.assertEqual(templates.validate_library(self.library), [])
        self.assertEqual(templates.validate_library(templates.empty_library()), [])
        self.assertEqual(templates.load_library(self.builtin, self.user), self.library)
        self.assertFalse(self.user.exists())

    def test_english_rejects_cjk_except_source_filename(self):
        for section, key in (("families", "description"), ("templates", "prompt_template"), ("sources", "observation")):
            invalid = copy.deepcopy(self.library)
            invalid[section][0][key] += " 中文"
            self.assertTrue(any("English" in e for e in templates.validate_library(invalid)))

    def test_no_assets_copy_or_html(self):
        values = ["/Users/sample/image.png", "C:\\Samples\\product.jpg", "https://example.test/image", "data:image/png;base64,AAA", "<div>product</div>", "image.png", "A" * 512]
        for value in values:
            invalid = copy.deepcopy(self.library)
            invalid["templates"][0]["generation"]["composition"] = value
            self.assertTrue(templates.validate_library(invalid), value)
        for key in ("copy", "headline", "body", "image_path", "panels"):
            invalid = copy.deepcopy(self.library)
            invalid["templates"][0]["layout"][key] = "Sample content"
            self.assertTrue(templates.validate_library(invalid), key)

    def test_no_source_path(self):
        for filename in ("/tmp/ref.png", "C:\\tmp\\ref.png", "../ref.png", "folder/ref.png", "file://ref.png"):
            invalid = copy.deepcopy(self.library)
            invalid["sources"][0]["filename"] = filename
            self.assertTrue(templates.validate_library(invalid), filename)

    def test_visual_review_required(self):
        invalid = copy.deepcopy(self.library)
        invalid["templates"][0]["review"]["visual_reviewed"] = False
        self.assertTrue(templates.validate_library(invalid))
        self.assertRaises(templates.TemplateError, self._import, invalid)
        self.assertFalse(self.user.exists())

    def test_malformed_structures_return_errors_not_exceptions(self):
        for invalid in (None, [], {}, {**templates.empty_library(), "sources": None}, {**templates.empty_library(), "templates": [None, []]}):
            self.assertTrue(templates.validate_library(invalid))
        for key, value in (("id", []), ("recipe", {}), ("family_id", []), ("revision", True), ("source_ids", None), ("kinds", [[]]), ("review", None)):
            invalid = copy.deepcopy(self.library)
            invalid["templates"][0][key] = value
            self.assertTrue(templates.validate_library(invalid), key)
        invalid = copy.deepcopy(self.library)
        invalid["sources"][0]["filename"] = "\ud800.png"
        self.assertTrue(templates.validate_library(invalid))

    def test_invalid_layout_and_nonfinite_values(self):
        for key, value in (("text_group_box", [0, 0, 2, 1]), ("headline_weight", 700), ("text_color", "red"), ("text_surface", {"kind": "solid", "opacity": float("nan")})):
            invalid = copy.deepcopy(self.library)
            invalid["templates"][0]["layout"][key] = value
            self.assertTrue(templates.validate_library(invalid), key)

    def test_canvas_variant_validation_rejects_invalid_and_overlapping_geometry(self):
        library = self._with_canvas_variants()
        self.assertEqual(templates.validate_library(library), [])
        for value in (None, {}, {"banner": {}}, {"square": {"text_group_box": [.05, .1, .35, .7]}}):
            invalid = copy.deepcopy(library)
            invalid["templates"][0]["layout"]["canvas_variants"] = value
            self.assertTrue(templates.validate_library(invalid))
        for key, value in (("product_region_norm", [.05, .1, .35, .7]), ("text_group_box", [0, 0, 2, 1]),
                           ("composition_note", ""), ("composition_note", "中文说明"), ("copy", "Borrowed sample")):
            invalid = copy.deepcopy(library)
            invalid["templates"][0]["layout"]["canvas_variants"]["square"][key] = value
            self.assertTrue(templates.validate_library(invalid), key)
        invalid = copy.deepcopy(library)
        invalid["templates"][0]["layout"]["product_region_norm"] = [.05, .1, .35, .7]
        self.assertTrue(templates.validate_library(invalid))

    def test_compilation_activates_only_current_canvas_variant(self):
        library = self._with_canvas_variants()
        family, template = library["families"][0], library["templates"][0]
        for shape, canvas in (("square", [2000, 2000]), ("portrait", [2000, 2600]), ("wide", [1464, 600])):
            result = templates.compile_template(family, template, self.context, {**self.job, "canvas": canvas})
            variant = template["layout"]["canvas_variants"][shape]
            layout, generation = result["brief"]["layout"], result["brief"]["generation"]
            self.assertEqual(layout["text_group_box"], variant["text_group_box"])
            self.assertEqual(layout["product_region_norm"], variant["product_region_norm"])
            self.assertEqual(generation["canvas_composition"], {"text_region_norm": variant["text_group_box"], "product_region_norm": variant["product_region_norm"], "notes": variant["composition_note"]})
            self.assertNotIn("canvas_variants", layout)
            self.assertNotIn("composition_note", layout)
            self.assertIn("canvas_variants", result["binding"]["template"]["snapshot"]["layout"])
            self.assertIsNone(templates.binding_issue(result["binding"]))

    def test_unused_variant_and_type_effects_do_not_change_generation(self):
        library = self._with_canvas_variants()
        original = templates.compile_template(library["families"][0], library["templates"][0], self.context, self.job)
        changed = copy.deepcopy(library)
        changed["templates"][0]["layout"]["canvas_variants"]["portrait"]["composition_note"] = "A revised portrait layout with the same protected subject."
        same_canvas = templates.compile_template(changed["families"][0], changed["templates"][0], self.context, self.job)
        self.assertEqual(original["brief"], same_canvas["brief"])
        self.assertNotEqual(original["binding"], same_canvas["binding"])
        changed["templates"][0]["layout"]["headline_weight"] = 600
        type_change = templates.compile_template(changed["families"][0], changed["templates"][0], self.context, self.job)
        self.assertEqual(original["brief"]["generation"], type_change["brief"]["generation"])
        self.assertNotEqual(original["brief"]["layout"], type_change["brief"]["layout"])
        portrait = templates.compile_template(changed["families"][0], changed["templates"][0], self.context, {**self.job, "canvas": [2000, 2600]})
        self.assertNotEqual(original["brief"]["generation"], portrait["brief"]["generation"])

    def test_all_builtin_canvas_compositions_are_disjoint(self):
        library = templates.load_library(templates.DEFAULT_BUILTIN, self.base / "absent-user.json")
        count = 0
        for template in library["templates"]:
            family = templates.get_family(library, template["family_id"])
            for shape, canvas in (("square", [2000, 2000]), ("portrait", [2000, 2600]), ("wide", [1464, 600])):
                result = templates.compile_template(family, template, self.context, {**self.job, "canvas": canvas})
                layout = result["brief"]["layout"]
                self.assertFalse(templates._boxes_overlap(layout["product_region_norm"], layout["text_group_box"]), (template["id"], shape))
                self.assertEqual(result["brief"]["generation"]["canvas_composition"]["product_region_norm"], layout["product_region_norm"])
                count += 1
        self.assertEqual(count, 81)

    def test_placeholder_validation(self):
        for suffix in ("{product.__class__}", "{product[0]}", "{product!r}", "{product:10}", "{unknown}", "{"):
            invalid = copy.deepcopy(self.library)
            invalid["templates"][0]["prompt_template"] += suffix
            self.assertTrue(templates.validate_library(invalid), suffix)

    def test_unknown_cross_references(self):
        invalid = copy.deepcopy(self.library)
        invalid["templates"][0]["source_ids"] = ["missing"]
        invalid["templates"][0]["family_id"] = "missing"
        self.assertTrue(templates.validate_library(invalid))
        self.assertEqual(templates.validate_library(invalid, check_references=False), [])
        self.assertRaises(templates.TemplateError, self._import, invalid)

    def test_exact_import_idempotent_and_no_empty_write(self):
        result = self._import(self.library)
        self.assertFalse(result["changed"])
        self.assertEqual(result["reused"]["templates"], [{"id": "warm-scene-sidebar", "revision": 1}])
        self.assertFalse(self.user.exists())

    def test_exact_cross_id_reuses_canonical_family_and_template(self):
        payload = copy.deepcopy(self.library)
        payload["sources"][0]["id"] = "new-source"
        payload["families"][0].update(id="other-family", source_ids=["new-source"])
        payload["templates"][0].update(id="other-template", family_id="other-family", source_ids=["new-source"])
        payload["templates"][0]["review"]["notes"] = "Another review of the identical design."
        result = self._import(payload)
        self.assertFalse(result["changed"])
        self.assertEqual(result["template_map"][0]["id"], "warm-scene-sidebar")
        self.assertEqual(result["family_map"][0]["id"], "warm-editorial")

    def test_similar_variant_is_not_merged(self):
        result = self._import(self._variant())
        self.assertTrue(result["changed"])
        self.assertTrue(result["similar_candidates"])
        self.assertEqual(len(templates.load_library(self.builtin, self.user)["templates"]), 2)

    def test_new_revision_appended_and_old_preserved(self):
        payload = self._variant()
        payload["templates"][0].update(id="warm-scene-sidebar", revision=2)
        self._import(payload)
        merged = templates.load_library(self.builtin, self.user)
        self.assertEqual(templates.get_template(merged, "warm-scene-sidebar")["revision"], 2)
        self.assertEqual(templates.get_template(merged, "warm-scene-sidebar", 1), self.library["templates"][0])
        self.assertEqual(json.loads(self.builtin.read_text()), self.library)

    def test_conflicting_revision_rejected_before_write(self):
        self._import(self._variant())
        before = self.user.read_bytes()
        payload = self._variant()
        payload["templates"][0]["generation"]["lighting"] = "A hard directional beam."
        self.assertRaises(templates.TemplateError, self._import, payload)
        self.assertEqual(self.user.read_bytes(), before)

    def test_revision_gap_rejected(self):
        payload = self._variant()
        payload["templates"][0].update(id="warm-scene-sidebar", revision=3)
        self.assertRaises(templates.TemplateError, self._import, payload)
        self.assertFalse(self.user.exists())

    def test_builtin_destination_rejected(self):
        self.assertRaises(templates.TemplateError, templates.import_library, self.library, self.builtin, self.builtin)
        self.assertRaises(templates.TemplateError, templates.load_library, self.builtin, self.builtin)

    def test_replace_failure_preserves_previous_library(self):
        self._import(self._variant())
        before = self.user.read_bytes()
        with patch("lc_style_reference.os.replace", side_effect=OSError("simulated replace failure")):
            self.assertRaises(OSError, self._import, self._variant("three"))
        self.assertEqual(before, self.user.read_bytes())
        self.assertEqual(list(self.base.glob(".*.tmp")), [])

    def test_corrupt_existing_library_is_not_replaced(self):
        self.user.write_text("{broken", encoding="utf-8")
        self.assertRaises(templates.TemplateError, self._import, self._variant())
        self.assertEqual(self.user.read_text(), "{broken")

    def test_concurrent_import_preserves_all_versions(self):
        script = Path(templates.__file__)
        processes = []
        for index in range(4):
            payload_path = self.base / f"payload-{index}.json"
            _write_json(payload_path, self._variant(f"variant-{index}"))
            processes.append(subprocess.Popen([sys.executable, str(script), "--builtin", str(self.builtin), "--user", str(self.user), "import", "--input", str(payload_path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
        for process in processes:
            stdout, stderr = process.communicate(timeout=20)
            self.assertEqual(process.returncode, 0, stdout + stderr)
        self.assertEqual(len(templates.load_library(self.builtin, self.user)["templates"]), 5)

    def test_category_gate_and_reason(self):
        ranked = templates.rank_families(self.library, self.context)
        self.assertEqual(ranked[0]["id"], "warm-editorial")
        self.assertTrue(ranked[0]["reasons"])
        self.assertEqual(templates.rank_families(self.library, {"product": "Cozy warm quantum sensor", "category": "laboratory", "style_preferences": "warm wood"}), [])

    def test_distinct_product_categories(self):
        library = copy.deepcopy(self.library)
        for identifier, category in (("technical-tool", "power_tool"), ("clean-beauty", "beauty_cosmetic")):
            family = copy.deepcopy(library["families"][0])
            family.update(id=identifier, categories=[category])
            library["families"].append(family)
        for product, expected in (("cordless drill", "technical-tool"), ("concealer makeup", "clean-beauty"), ("shelf decor", "warm-editorial")):
            self.assertEqual(templates.rank_families(library, {"product": product})[0]["id"], expected)

    def test_real_builtin_category_and_intent_compatibility(self):
        library = templates.load_library(templates.DEFAULT_BUILTIN, self.base / "absent-user.json")
        for context, expected in (({"product": "cordless drill", "category": "power_tool"}, "active-functional"),
                                  ({"product": "Concealer makeup", "category": "beauty_cosmetic"}, "soft-beauty"),
                                  ({"product": "wood shelf decor", "category": "home_decor"}, "daylight-home"),
                                  ({"product": "wireless headphones"}, "dark-precision")):
            self.assertEqual(templates.rank_families(library, context)[0]["id"], expected)
        for family, intent, expected in (("active-functional", "Show cutting action", "functional-contact-action"),
                                          ("daylight-home", "Show four scenes", "daylight-four-scene-grid"),
                                          ("warm-tactile-home", "Show visual detail", "warm-tactile-macro-rail")):
            ranked = templates.rank_templates(library, family, {**self.job, "selling_job": intent})
            self.assertIn(expected, [r["id"] for r in ranked])

    def test_kind_shape_and_recipe_soft_preference(self):
        for kind, canvas in (("listing", [2000, 2000]), ("secondary", [2000, 2600]), ("a_plus", [1464, 600])):
            job = {**self.job, "kind": kind, "canvas": canvas}
            self.assertEqual(templates.rank_templates(self.library, "warm-editorial", job)[0]["id"], "warm-scene-sidebar")
        self.assertEqual(templates.rank_templates(self.library, "warm-editorial", {"kind": "main"}), [])
        library = copy.deepcopy(self.library)
        library["templates"][0]["canvas_shapes"] = ["portrait"]
        self.assertEqual(templates.rank_templates(library, "warm-editorial", self.job), [])

    def test_dimensions_and_faq_never_forced_to_lifestyle(self):
        for intent in ("Show dimensions in a scene", "Answer product FAQ", "Installation steps", "What is included"):
            self.assertEqual(templates.rank_templates(self.library, "warm-editorial", {**self.job, "selling_job": intent}), [], intent)

    def test_no_original_images_needed_for_compile_or_binding(self):
        family, template = self.library["families"][0], self.library["templates"][0]
        with patch.object(Path, "open", side_effect=AssertionError("No filesystem reads allowed")):
            result = templates.compile_template(family, template, self.context, self.job)
            self.assertIsNone(templates.binding_issue(result["binding"]))
        self.assertIn("Wood shelf decor", result["brief"]["generation"]["resolved_prompt"])
        self.assertNotIn("Approved project copy", json.dumps(result))
        self.assertNotIn("content_hash", result["brief"]["generation"])
        self.assertNotIn("revision", result["brief"]["generation"])

    def test_runtime_parameters_can_be_other_languages(self):
        result = templates.compile_template(self.library["families"][0], self.library["templates"][0], {"product": "真实商品"}, {**self.job, "scene": "室内", "selling_job": "用途"})
        self.assertIn("真实商品", result["brief"]["generation"]["resolved_prompt"])

    def test_binding_is_frozen_and_tampering_detected(self):
        result = templates.compile_template(self.library["families"][0], self.library["templates"][0], self.context, self.job)
        self.library["templates"][0]["layout"]["text_color"] = "#111111"
        self.assertIsNone(templates.binding_issue(result["binding"]))
        result["binding"]["template"]["snapshot"]["layout"]["text_color"] = "#EEEEEE"
        self.assertIn("Changed", templates.binding_issue(result["binding"]))
        for invalid in (None, [], {}, {"schema_version": 1, "family": None, "template": None}):
            self.assertIsNotNone(templates.binding_issue(invalid))

    def test_typography_and_layout_guidance_do_not_change_generation(self):
        original = templates.compile_template(self.library["families"][0], self.library["templates"][0], self.context, self.job)
        changed = copy.deepcopy(self.library)
        changed["families"][0]["style"]["typography"] = "Use a sans display hierarchy."
        changed["templates"][0]["layout"]["text_color"] = "#111111"
        changed["templates"][0]["layout"]["headline_family"] = "sans"
        changed["templates"][0]["adaptation_rules"].append("Move the local heading after copy measurement.")
        changed["templates"][0]["revision"] = 2
        result = templates.compile_template(changed["families"][0], changed["templates"][0], self.context, self.job)
        self.assertEqual(original["brief"]["generation"], result["brief"]["generation"])
        self.assertNotEqual(original["brief"]["layout"], result["brief"]["layout"])
        self.assertNotEqual(original["binding"], result["binding"])

    def test_compile_respects_native_route_and_rejects_main_none(self):
        result = templates.compile_template(self.library["families"][0], self.library["templates"][0], self.context, {**self.job, "text_mode": "model_native"})
        self.assertIn("supplied separately", result["brief"]["generation"]["text_policy"])
        for job in ({**self.job, "kind": "main"}, {**self.job, "text_mode": "none"}, {**self.job, "canvas": [0, 100]}):
            self.assertRaises(templates.TemplateError, templates.compile_template, self.library["families"][0], self.library["templates"][0], self.context, job)

    def test_cli_output_is_single_json(self):
        result = subprocess.run([sys.executable, templates.__file__, "--builtin", str(self.builtin), "--user", str(self.user), "validate"], capture_output=True, text=True, check=True)
        self.assertTrue(json.loads(result.stdout)["valid"])
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
