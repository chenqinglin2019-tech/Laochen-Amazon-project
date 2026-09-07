"""Design-first regressions; generated-looking images here are synthetic test fixtures."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image, ImageDraw
import lc_typography as t
import lc_project_contracts as c
import lc_layout as l
import lc_title_effects as e


def job_fixture():
    return {"id": "fixture", "kind": "listing", "text_mode": "local_overlay", "canvas": [1000, 1000],
            "layout_input": "base.png", "output_product_bbox_norm": [.6, .4, .3, .5],
            "layout": {"version": 3, "recipe": "photo_overlay", "text_groups": [
                {"id": "title", "headline": "Cozy Frights", "box": [.08, .06, .8, .17]},
                {"id": "body", "body": "A little ghostly charm.", "box": [.08, .25, .8, .1]}]},
            "_project_style": {**t.default_contract(), "color_roles": {"headline": "#F4D8A5", "body": "#E9D7B4", "accent": "#E59A35"},
                               "font_roles": {"headline": {"family": "serif", "weight": 400}}}}


class DesignFirstTests(unittest.TestCase):
    def test_no_palette_or_reduction_is_invented(self):
        self.assertEqual(c.default_style_contract()["color_roles"], {})
        self.assertEqual(c.default_style_contract()["font_roles"], {})
        job = job_fixture(); job["_project_style"] = t.default_contract()
        with self.assertRaisesRegex(l.LayoutError, "DESIGN_COLOR_REQUIRED"): l.resolve_layout_defaults(job)

    def test_intentionally_text_free_scene_needs_no_glyph_proofs(self):
        job = job_fixture(); job["layout"]["text_groups"] = []
        self.assertFalse(t.enabled(job))
        self.assertEqual(l.resolve_layout_defaults(job)["text_groups"], [])

    def test_design_adjustment_records_survive_cache_rebuild(self):
        job = job_fixture()
        first = t.decision(job, l.resolve_layout_defaults(job))
        job["layout_result"] = {"typography_decision": first}
        job["layout"]["text_groups"][0]["text_color"] = "#F6E5C0"
        second = t.decision(job, l.resolve_layout_defaults(job))
        self.assertEqual(len(second["adjustments"]), 1)
        self.assertFalse(second["adjustments"][0]["automatic"])
        job["layout_result"]["typography_decision"] = second
        self.assertEqual(t.decision(job, l.resolve_layout_defaults(job))["adjustments"], second["adjustments"])

    def test_explicit_project_and_brief_precedence_is_stable(self):
        job = job_fixture(); job["design_brief"] = {"layout": {"text_color": "#FFFFFF", "headline_family": "sans", "headline_weight": 700}}
        before = copy.deepcopy(job)
        for _ in range(2):
            g = l.resolve_layout_defaults(job)["text_groups"][0]
            self.assertEqual((g["text_color"], g["headline_family"], g["headline_weight"]), ("#F4D8A5", "serif", 400))
        self.assertEqual(job, before)
        job["layout"]["text_color"] = "#AABBCC"
        self.assertEqual(l.resolve_layout_defaults(job)["text_groups"][0]["text_color"], "#AABBCC")
        job["layout"]["text_groups"][0].update(text_color="#BBDDAA", headline_family="sans", headline_weight=700)
        g = l.resolve_layout_defaults(job)["text_groups"][0]
        self.assertEqual((g["text_color"], g["headline_family"], g["headline_weight"]), ("#BBDDAA", "sans", 700))

    def test_other_products_use_own_ink_and_no_invented_surface(self):
        for ink, font in (("#25352A", "serif"), ("#20262C", "sans")):
            job = job_fixture(); job["_project_style"].update(color_roles={"headline": ink, "body": ink}, font_roles={"headline": {"family": font, "weight": 400}})
            g = l.resolve_layout_defaults(job)["text_groups"][0]
            self.assertEqual(g["text_color"], ink); self.assertEqual(g["headline_family"], font)
            self.assertNotIn("surface", g)
            self.assertEqual(job["layout"]["text_groups"][1]["body"], "A little ghostly charm.")

    def test_invalid_role_and_adjustment_contracts(self):
        for value in (None, [], {"headline": None}, {"unsupported": "#FFFFFF"}):
            self.assertTrue(c.validate_project_contracts({"style_contract": {**t.default_contract(), "color_roles": value}}))
        for value in (None, {}, [None], [[]], ["unbounded"]):
            self.assertTrue(t.validate_contract({**t.default_contract(), "allowed_adjustments": value}))

    def test_core_ignores_unused_bright_box_pixels_and_antialias_fringe(self):
        bg = Image.new("RGB", (40, 30), "white"); ImageDraw.Draw(bg).rectangle((10, 10, 19, 19), fill="#1F1108")
        fg = bg.copy(); ImageDraw.Draw(fg).rectangle((10, 10, 19, 19), fill="#F4D8A5")
        mask = Image.new("L", bg.size); ImageDraw.Draw(mask).rectangle((10, 10, 19, 19), fill=255)
        boxes = [{"id": "actual", "kind": "text", "bbox": {"x": 0, "y": 0, "width": 40, "height": 30}}]
        self.assertTrue(t.raster_contrast(fg, bg, mask, boxes)[0]["passed"])
        self.assertFalse(t.raster_contrast(bg, bg, mask, boxes)[0]["passed"])
        mask.putpixel((0, 0), 100)
        self.assertEqual(t.raster_contrast(fg, bg, mask, boxes)[0]["core_pixels"], 100)

    def test_only_failed_jpeg_retries_and_failure_never_approves(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp); job = job_fixture(); job.update(export={"quality": 92}, image_sha256="fixture",
                ai_disclosure={"human_source": "none", "notes": "Synthetic fixture", "reviewed_image_sha256": "fixture"})
            image = Image.new("RGB", (1000, 1000), "#221A12")
            with patch.object(t, "proof_current", return_value=True), patch.object(t, "check_export", side_effect=[{"passed": False, "quality": 92}, {"passed": True, "quality": 95}]) as check:
                result = t.export_checked(image, job, base, base / "final.jpg")
            self.assertEqual(check.call_count, 2); self.assertEqual(result["encoding"]["quality"], 95)
            with patch.object(t, "proof_current", return_value=True), patch.object(t, "check_export", return_value={"passed": False, "quality": 95}):
                with self.assertRaisesRegex(ValueError, "FINAL_GLYPH_CONTRAST"): t.export_checked(image, job, base, base / "final.jpg")
            self.assertFalse(job["export_result"]["typography"]["passed"])


@unittest.skipUnless(os.environ.get("LC_LAYOUT_BROWSER_TEST") == "1", "opt-in pinned browser")
class TypographyBrowserTests(unittest.TestCase):
    def test_actual_ink_proofs_and_encoded_pixels(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp); Image.new("RGB", (1000, 1000), "#251409").save(base / "base.png")
            good = job_fixture(); bad = copy.deepcopy(good); bad["id"] = "bad"
            bad["layout"]["text_groups"][0]["text_color"] = "#44200B"
            before = copy.deepcopy(good); results = l.render_batch({}, base, [good, bad])
            self.assertTrue(results["fixture"]["passed"], results["fixture"])
            self.assertFalse(results["bad"]["passed"]); self.assertEqual(good, before)
            self.assertEqual(results["fixture"]["typography_decision"]["resolved_groups"][0]["text_color"], "#F4D8A5")
            good.update(layout_result=results["fixture"], export={"quality": 92}, image_sha256="fixture",
                ai_disclosure={"human_source": "none", "reviewed_image_sha256": "fixture", "notes": "Synthetic fixture"})
            with Image.open(base / results["fixture"]["output_path"]) as image: exported = t.export_checked(image, good, base, base / "final.jpg")
            good["export_result"] = exported
            self.assertTrue(exported["typography"]["passed"])
            self.assertEqual(t.export_evidence_issues({}, good, base, base / "final.jpg"), [])
            with (base / "final.jpg").open("ab") as stream: stream.write(b"tampered")
            self.assertTrue(t.export_evidence_issues({}, good, base, base / "final.jpg"))

    def test_effect_body_edit_reuses_candidate_and_preserves_product_pixels(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp); Image.new("RGB", (1000, 1000), "#251409").save(base / "base.png")
            job = job_fixture(); job["source_reference_ids"] = ["fixture"]
            job["layout"]["text_groups"][0]["decorative_effect"] = {"kind": "surface_emboss", "purpose": "decorative",
                "reason": "Synthetic regression only", "surface": "test wall", "material_lighting": "warm right-side light",
                "allowed_bbox_norm": [.07, .055, .83, .18], "semantic_review": {"decorative_only": True, "contains_brand": False, "contains_facts": False}}
            m = {"references": [{"id": "fixture", "path": "base.png", "provenance": {"kind": "real_photo", "notes": "Synthetic stand-in only"}}]}
            result = l.render_batch(m, base, [job])[job["id"]]
            self.assertTrue(result["passed"], result); self.assertFalse(result["title_effect"]["applied"])
            with Image.open(base / result["output_path"]) as image: flat = image.convert("RGB")
            flat.save(base / "candidate.png")
            mask = Image.new("L", flat.size)
            # Deliberately broad synthetic adoption area still excludes product and body.
            ImageDraw.Draw(mask).rectangle((75, 58, 890, 230), fill=255); mask.save(base / "mask.png")
            e.attempt_event(m, base, job, "tool_started", attempt_id="synthetic-only", at=1)
            e.attempt_event(m, base, job, "tool_returned", attempt_id="synthetic-only", at=2)
            e.ingest(m, base, job, base / "candidate.png", base / "mask.png", attempt_id="synthetic-only")
            fp = l.layout_fingerprint(m, job, base)
            result = l.render_batch(m, base, [job])[job["id"]]
            self.assertTrue(result["passed"], result); self.assertTrue(result["title_effect"]["applied"], result)
            self.assertEqual(l.layout_fingerprint(m, job, base), fp)
            binding = result["title_effect"]["binding"]
            job["layout"]["text_groups"][1]["body"] = "A warm indoor glow."
            result = l.render_batch(m, base, [job])[job["id"]]
            self.assertTrue(result["title_effect"]["applied"], result)
            self.assertNotEqual(result["title_effect"]["binding"], binding)
            with Image.open(base / result["output_path"]) as image:
                self.assertEqual(image.crop((600, 400, 900, 900)).tobytes(), flat.crop((600, 400, 900, 900)).tobytes())
            self.assertEqual(len(job["title_effect_attempts"]), 1); self.assertTrue(e.review_issues(job, None))

if __name__ == "__main__": unittest.main()
