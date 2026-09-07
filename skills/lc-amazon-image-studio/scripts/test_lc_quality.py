"""Regression tests for source-region evidence and render routing (no model calls)."""
from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

import lc_quality as quality


def reference(rid="front", *, clarity="clear", size=(1800, 1800), view="front", role="whole_product_reference"):
    ref = {"id": rid, "path": f"{rid}.png", "role": role, "view": view,
           "sha256": (rid.encode().hex() * 64)[:64], "product_bbox_norm": [0, 0, 1, 1], "product_pixel_size": list(size)}
    ref["quality_review"] = {"clarity": clarity, "evidence": "sufficient", "defects": [], "notes": "Visually inspected source region",
                             "reviewed_sha256": ref["sha256"], "reviewed_region_fingerprint": quality.source_region_fingerprint(ref)}
    return ref


def project(refs=None, *, degradation="none", fit="matched", evidence="sufficient"):
    refs = refs if refs is not None else [reference()]
    manifest = {"references": refs, "product_truth": {"safe_upscale_ratio": 1.25, "max_marginal_upscale_ratio": 1.75},
                "critical_details": [], "critical_detail_census_completed": False,
                "jobs": [{"id": "main", "view": "front", "canvas": [2000, 2000], "requires_fine_detail": False,
                          "target_product_bbox_norm": [0.1, 0.1, 0.8, 0.8], "source_reference_ids": [r["id"] for r in refs],
                          "source_assessment": {"scene_fit": fit, "evidence": evidence, "degradation": degradation,
                                                "reason": "Inspected target-size crop and product evidence."}}]}
    review_job(manifest)
    return manifest


def review_job(manifest, index=0):
    job = manifest["jobs"][index]
    decision = quality.decide_job(manifest, job)
    job["source_assessment"]["reviewed_reference_hashes"] = decision["required_reference_hashes"]
    job["source_assessment"]["reviewed_context_fingerprint"] = decision["assessment_context_fingerprint"]


def decide(manifest):
    return quality.decide_job(manifest, manifest["jobs"][0])


class RoutingTests(unittest.TestCase):
    def assertRoute(self, manifest, mode, action=None):
        result = decide(manifest)
        self.assertEqual([], result["blocked_reasons"])
        self.assertEqual(mode, result["recommended_mode"])
        if action:
            self.assertEqual(action, result["suggested_action"])
        return result

    def test_clear_matching_product_reuses_pixels(self):
        result = self.assertRoute(project(), "pixel_composite")
        self.assertEqual("front", result["pixel_source_reference_id"])
        self.assertAlmostEqual(0.8889, result["effective_upscale_ratio"])

    def test_high_resolution_blurred_product_redraws_same_view(self):
        manifest = project([reference(clarity="blurred", size=(8000, 8000))], degradation="global")
        self.assertRoute(manifest, "reference_generate", "redraw_same_view")

    def test_wide_product_uses_actual_contain_scale_not_stretch_scale(self):
        result = self.assertRoute(project([reference(size=(1800, 600))]), "pixel_composite")
        self.assertAlmostEqual(0.8889, result["effective_upscale_ratio"])

    def test_high_resolution_background_never_overrides_product_region(self):
        ref = reference(clarity="blurred", size=(300, 300))
        ref["image_size"] = [8000, 8000]
        self.assertRoute(project([ref], degradation="global"), "reference_generate", "redraw_same_view")

    def test_clear_small_product_redraws_without_pixel_limit_block(self):
        self.assertRoute(project([reference(size=(300, 300))]), "reference_generate", "redraw_from_confirmed_evidence")

    def test_fine_detail_does_not_use_marginal_pixel_upscale(self):
        manifest = project([reference(size=(1100, 1100))])
        self.assertRoute(manifest, "pixel_composite")
        manifest["jobs"][0]["requires_fine_detail"] = True
        review_job(manifest)
        self.assertRoute(manifest, "reference_generate")

    def test_light_softness_requires_conservative_cleanup_and_review(self):
        self.assertRoute(project([reference(clarity="mild_softness")], degradation="mild"),
                         "reference_edit", "conservative_cleanup_then_review")

    def test_local_defect_wins_over_other_clear_sources(self):
        manifest = project([reference("first"), reference("second", size=(4000, 4000))], degradation="localized")
        self.assertRoute(manifest, "reference_edit", "repair_local_region")

    def test_environment_edit(self):
        self.assertRoute(project(fit="local_change"), "reference_edit", "edit_environment")

    def test_new_view_uses_all_evidence_and_requires_new_output_positions(self):
        manifest = project([reference("front"), reference("back", view="back")], fit="new_view")
        manifest["jobs"][0]["target_view"] = "three_quarter"
        review_job(manifest)
        result = self.assertRoute(manifest, "reference_generate", "generate_target_view")
        self.assertTrue(result["require_output_detail_relocation"])
        self.assertEqual(["front", "back"], result["selected_reference_ids"])

    def test_named_view_difference_can_be_explicitly_reviewed_as_match(self):
        manifest = project([reference(view="front_photo")])
        self.assertIn("SOURCE_MATCHED_REFERENCE_REVIEW_REQUIRED", decide(manifest)["blocked_reasons"])
        manifest["jobs"][0]["source_assessment"]["matched_reference_ids"] = ["front"]
        review_job(manifest)
        self.assertRoute(manifest, "pixel_composite")

    def test_selects_usable_product_reference_not_first_detail(self):
        refs = [reference("label", size=(60, 60), role="critical_detail_reference"), reference("whole", size=(2500, 2500))]
        result = self.assertRoute(project(refs), "pixel_composite")
        self.assertEqual("whole", result["pixel_source_reference_id"])

    def test_bad_first_whole_reference_does_not_block_good_alternative(self):
        refs = [reference("bad", clarity="blurred"), reference("good")]
        result = self.assertRoute(project(refs), "pixel_composite")
        self.assertEqual("good", result["pixel_source_reference_id"])
        self.assertEqual("blurred", result["source_quality_by_reference"]["bad"]["clarity"])

    def test_selected_pixel_reference_cannot_silently_swap(self):
        manifest = project([reference("small", size=(100, 100)), reference("large", size=(3000, 3000))])
        manifest["jobs"][0]["pixel_source_reference_id"] = "small"
        review_job(manifest)
        self.assertRoute(manifest, "reference_generate")

    def test_unknown_and_insufficient_evidence_block(self):
        for evidence, code in (("unknown", "SOURCE_JOB_REVIEW_REQUIRED"), ("insufficient", "SOURCE_JOB_EVIDENCE_INSUFFICIENT")):
            with self.subTest(evidence=evidence):
                manifest = project(evidence=evidence)
                self.assertIn(code, decide(manifest)["blocked_reasons"])

    def test_no_automatic_metric_pass_for_smooth_or_sharpened_product(self):
        ref = reference(clarity="unknown")
        ref["quality_metrics"] = {"edge_signal": 900, "inspection_flags": []}
        manifest = project([ref])
        self.assertIn("SOURCE_REVIEW_REQUIRED:front", decide(manifest)["blocked_reasons"])

    def test_source_hash_and_crop_changes_invalidate_review(self):
        for key, value, expected in (("sha256", "changed", "SOURCE_REVIEW_STALE:front"),
                                     ("product_bbox_norm", [0.1, 0.1, 0.8, 0.8], "SOURCE_REGION_REVIEW_STALE:front")):
            with self.subTest(key=key):
                manifest = project()
                manifest["references"][0][key] = value
                self.assertIn(expected, decide(manifest)["blocked_reasons"])

    def test_target_changes_invalidate_assessment_but_not_status_changes(self):
        manifest = project()
        baseline = decide(manifest)["assessment_context_fingerprint"]
        manifest["jobs"][0]["status"] = "blocked"
        manifest["jobs"][0]["blocked_reason"] = "Something"
        self.assertEqual(baseline, decide(manifest)["assessment_context_fingerprint"])
        manifest["jobs"][0]["canvas"] = [2000, 2600]
        self.assertIn("SOURCE_ASSESSMENT_CONTEXT_STALE", decide(manifest)["blocked_reasons"])

    def test_one_blocked_job_does_not_modify_other_job_or_global_state(self):
        manifest = project(evidence="insufficient")
        before = copy.deepcopy(manifest)
        decide(manifest)
        self.assertEqual(before, manifest)

    def test_alternate_detail_reference_supports_required_detail(self):
        manifest = project([reference(clarity="blurred")], degradation="global")
        manifest["references"].append(reference("port", size=(200, 200), role="critical_detail_reference"))
        manifest["critical_details"] = [{"id": "usb", "priority": "P0", "evidence_level": "visual_confirmed", "visual_confirmation": "confirmed",
            "visibility": {"main": "required"}, "locations": [{"reference_id": "port", "view": "detail", "bbox_in_product_norm": [0.1, 0.1, 0.8, 0.8]}]}]
        review_job(manifest)
        result = self.assertRoute(manifest, "reference_generate")
        self.assertEqual(["front", "port"], result["selected_reference_ids"])
        self.assertIn("port", result["required_reference_hashes"])

    def test_unreadable_required_detail_blocks_only_that_job(self):
        manifest = project()
        manifest["critical_details"] = [{"id": "label", "priority": "P1", "evidence_level": "visual_confirmed", "visual_confirmation": "confirmed",
            "visibility": {"main": "required"}, "locations": [{"reference_id": "front", "bbox_in_product_norm": [0, 0, 0.001, 0.001]}]}]
        review_job(manifest)
        self.assertIn("SOURCE_REQUIRED_DETAIL_UNVERIFIABLE:label", decide(manifest)["blocked_reasons"])
        manifest["critical_details"][0]["visibility"]["main"] = "hidden"
        review_job(manifest)
        self.assertRoute(manifest, "pixel_composite")

    def test_generated_master_cannot_become_unbacked_product_truth(self):
        manifest = project()
        manifest["references"][0]["provenance"] = {"kind": "generated", "qa_verdict": "pass"}
        review_job(manifest)
        self.assertIn("SOURCE_MASTER_EVIDENCE_UNVERIFIED:front", decide(manifest)["blocked_reasons"])

    def test_generated_master_requires_current_real_evidence(self):
        real = reference("real")
        master = reference("master")
        master["provenance"] = {"kind": "generated", "qa_verdict": "pass", "source_reference_ids": ["real"],
                                "reviewed_source_hashes": {"real": real["sha256"]}}
        manifest = project([master])
        manifest["references"].append(real)
        review_job(manifest)
        result = self.assertRoute(manifest, "pixel_composite")
        self.assertIn("real", result["selected_reference_ids"])
        self.assertIn("real", result["required_reference_hashes"])
        real["sha256"] = "changed"
        self.assertIn("SOURCE_MASTER_EVIDENCE_UNVERIFIED:master", decide(manifest)["blocked_reasons"])
        self.assertIn("SOURCE_ASSESSMENT_CONTEXT_STALE", decide(manifest)["blocked_reasons"])

    def test_cyclic_generated_provenance_blocks_without_recursing_forever(self):
        a, b = reference("a"), reference("b")
        a["provenance"] = {"kind": "generated", "source_reference_ids": ["b"], "qa_verdict": "pass"}
        b["provenance"] = {"kind": "generated", "source_reference_ids": ["a"], "qa_verdict": "pass"}
        manifest = project([a, b])
        self.assertIn("SOURCE_MASTER_EVIDENCE_UNVERIFIED:a", decide(manifest)["blocked_reasons"])

    def test_invalid_provenance_types_are_schema_errors(self):
        manifest = project()
        manifest["references"][0]["provenance"] = None
        self.assertEqual(1, len(quality.validate_quality(manifest)))
        manifest["references"][0]["provenance"] = {"kind": "generated", "source_reference_ids": None}
        manifest["jobs"][0]["source_assessment"]["matched_reference_ids"] = ["front"]
        self.assertEqual(1, len(quality.validate_quality(manifest)))

    def test_schema_rejects_null_and_wrong_types_without_crash(self):
        manifest = project()
        self.assertEqual([], quality.validate_quality(manifest))
        manifest["references"][0]["quality_review"]["clarity"] = []
        manifest["jobs"][0]["source_assessment"]["degradation"] = None
        manifest["jobs"][0]["source_assessment"]["reviewed_reference_hashes"] = []
        self.assertEqual(3, len(quality.validate_quality(manifest)))


class SourceCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        # Sharp background, deliberately smooth product centre. A full-image
        # sharpness signal would be misleading here.
        image = Image.new("RGB", (400, 400), "white")
        draw = ImageDraw.Draw(image)
        for x in range(0, 400, 8):
            draw.rectangle((x, 0, x + 3, 399), fill="black")
        draw.rectangle((100, 100, 299, 299), fill="#888888")
        image.save(self.base / "front.png")
        self.manifest = project()
        self.manifest["references"][0]["product_bbox_norm"] = [0.25, 0.25, 0.5, 0.5]
        self.manifest["jobs"][0]["canvas"] = [400, 520]

    def tearDown(self):
        self.temp.cleanup()

    def test_metrics_use_native_product_not_high_detail_background(self):
        quality.assess_sources(self.manifest, self.base)
        ref = self.manifest["references"][0]
        self.assertEqual([400, 400], ref["image_size"])
        self.assertEqual([200, 200], ref["product_pixel_size"])
        self.assertEqual(0, ref["quality_metrics"]["edge_signal"])
        self.assertTrue(ref["quality_metrics"]["screening_only"])
        self.assertEqual(9, len(ref["quality_metrics"]["tiles"]))
        with Image.open(self.base / ref["quality_metrics"]["product_crop_path"]) as crop:
            self.assertEqual((200, 200), crop.size)
        preview = ref["quality_metrics"]["target_previews"][0]
        with Image.open(self.base / preview["path"]) as output:
            self.assertEqual((400, 520), output.size)
        with Image.open(self.base / preview["thumbnail_path"]) as output:
            self.assertEqual((360, 468), output.size)

    def test_cache_reuses_unchanged_artifacts(self):
        quality.assess_sources(self.manifest, self.base)
        root = self.base / "review" / "source_quality"
        times = {str(p): p.stat().st_mtime_ns for p in root.iterdir()}
        quality.assess_sources(self.manifest, self.base)
        self.assertEqual(times, {str(p): p.stat().st_mtime_ns for p in root.iterdir()})

    def test_corrupted_cache_artifact_regenerates(self):
        quality.assess_sources(self.manifest, self.base)
        path = self.base / self.manifest["references"][0]["quality_metrics"]["product_crop_path"]
        path.write_bytes(b"corrupted")
        quality.assess_sources(self.manifest, self.base)
        with Image.open(path) as crop:
            self.assertEqual((200, 200), crop.size)

    def test_target_change_reuses_native_crop_but_rebuilds_preview(self):
        quality.assess_sources(self.manifest, self.base)
        metrics = copy.deepcopy(self.manifest["references"][0]["quality_metrics"])
        crop_path = self.base / metrics["product_crop_path"]
        previous_time = crop_path.stat().st_mtime_ns
        self.manifest["jobs"][0]["canvas"] = [400, 400]
        quality.assess_sources(self.manifest, self.base)
        updated = self.manifest["references"][0]["quality_metrics"]
        self.assertEqual(metrics["product_crop_path"], updated["product_crop_path"])
        self.assertEqual(previous_time, crop_path.stat().st_mtime_ns)
        self.assertNotEqual(metrics["target_previews"][0]["path"], updated["target_previews"][0]["path"])

    def test_detail_crop_available_before_census_completion(self):
        self.manifest["critical_details"] = [{"id": "label", "priority": "P1", "visibility": {"main": "required"},
            "locations": [{"reference_id": "front", "bbox_in_product_norm": [0.1, 0.1, 0.2, 0.1]}]}]
        quality.assess_sources(self.manifest, self.base)
        self.assertFalse(self.manifest["critical_detail_census_completed"])
        detail = self.manifest["references"][0]["quality_metrics"]["detail_regions"][0]
        self.assertEqual([40, 20], detail["pixel_size"])
        self.assertTrue((self.base / detail["path"]).is_file())
        self.assertTrue(self.manifest["jobs"][0]["assessment_context_fingerprint"])

    def test_blur_and_sharpening_scores_do_not_complete_visual_review(self):
        for name, transform in (
            ("blur", lambda im: im.filter(ImageFilter.GaussianBlur(5))),
            ("fake_upscale", lambda im: im.resize((30, 30)).resize((400, 400))),
            ("sharpen", lambda im: im.filter(ImageFilter.UnsharpMask(4, 500, 0))),
        ):
            with self.subTest(name=name):
                with Image.open(self.base / "front.png") as source:
                    transform(source).save(self.base / f"{name}.png")
                ref = self.manifest["references"][0]
                ref["path"] = f"{name}.png"
                ref["quality_review"] = {"clarity": "unknown", "evidence": "unknown"}
                quality.assess_sources(self.manifest, self.base)
                self.assertEqual("unknown", ref["quality_review"]["clarity"])
                self.assertIn("SOURCE_REVIEW_REQUIRED:front", decide(self.manifest)["blocked_reasons"])

    def test_jpeg_compression_and_local_blur_remain_reviewable_inputs(self):
        with Image.open(self.base / "front.png") as original:
            original.save(self.base / "compressed.jpg", quality=2)
            local = original.copy()
            local.paste(original.crop((0, 0, 200, 400)).filter(ImageFilter.GaussianBlur(8)), (0, 0))
            local.save(self.base / "local.png")
        for filename in ("compressed.jpg", "local.png"):
            with self.subTest(filename=filename):
                self.manifest["references"][0]["path"] = filename
                self.manifest["references"][0]["quality_review"] = {"clarity": "unknown", "evidence": "unknown"}
                quality.assess_sources(self.manifest, self.base)
                self.assertEqual("unknown", self.manifest["references"][0]["quality_review"]["clarity"])

    def test_invalid_region_rejected(self):
        self.manifest["references"][0]["product_bbox_norm"] = [0, 0, 0, 1]
        with self.assertRaises(ValueError):
            quality.assess_sources(self.manifest, self.base)


class LayerSourceTests(unittest.TestCase):
    def setUp(self):
        SourceCacheTests.setUp(self)
        self.manifest["jobs"][0]["product_layers"] = [{"reference_id": "front", "opaque_rectangle": True}]

    def tearDown(self):
        SourceCacheTests.tearDown(self)

    def inspect(self, review_ids=None):
        quality.assess_sources(self.manifest, self.base)
        for ref in self.manifest["references"]:
            if review_ids is None or ref["id"] in review_ids:
                ref["quality_review"] = {"clarity": "clear", "evidence": "sufficient", "notes": "Inspected actual layer source",
                    "reviewed_sha256": ref["sha256"], "reviewed_region_fingerprint": ref["quality_metrics"]["region_fingerprint"]}
        review_job(self.manifest)
        return decide(self.manifest)

    def bind_cutout(self, index=0):
        job = self.manifest["jobs"][0]
        layer = job["product_layers"][index]
        record = job["layer_asset_hashes"][index]
        ref = next(ref for ref in self.manifest["references"] if ref["id"] == layer["reference_id"])
        layer["source_binding"] = {"reviewed": True, "reviewed_asset_sha256": record["asset_sha256"],
            "reviewed_mask_sha256": record["mask_sha256"], "source_reference_hashes": {ref["id"]: ref["sha256"]}}
        review_job(self.manifest)

    def test_original_layer_uses_selected_reviewed_product(self):
        result = self.inspect()
        self.assertEqual([], result["blocked_reasons"])
        self.assertEqual("pixel_composite", result["recommended_mode"])
        self.assertEqual("front", result["pixel_source_reference_id"])

    def test_unreviewed_actual_layer_cannot_hide_behind_clear_unused_front(self):
        Image.new("RGB", (400, 400), "red").save(self.base / "back.png")
        bad = reference("back", clarity="unknown", view="back")
        bad["quality_review"] = {"clarity": "unknown", "evidence": "unknown"}
        self.manifest["references"].append(bad)
        self.manifest["jobs"][0]["product_layers"][0]["reference_id"] = "back"
        result = self.inspect(review_ids={"front"})
        self.assertIn("back", result["selected_reference_ids"])
        self.assertIn("SOURCE_LAYER:0:CLEAR_REVIEWED_SOURCE_REQUIRED", result["layer_blockers"])
        self.assertIn("SOURCE_LAYER:0:TARGET_VIEW_NOT_MATCHED", result["layer_blockers"])

    def test_clear_but_wrong_view_layer_is_rejected(self):
        Image.new("RGB", (400, 400), "red").save(self.base / "back.png")
        self.manifest["references"].append(reference("back", view="back"))
        self.manifest["jobs"][0]["product_layers"][0]["reference_id"] = "back"
        result = self.inspect()
        self.assertIn("SOURCE_LAYER:0:TARGET_VIEW_NOT_MATCHED", result["layer_blockers"])
        self.assertIn("SOURCE_LAYER:0:SELECTED_PIXEL_REFERENCE_MISMATCH", result["layer_blockers"])

    def test_distinct_cutout_requires_pixel_source_binding(self):
        Image.new("RGBA", (400, 400), (10, 20, 30, 200)).save(self.base / "cutout.png")
        self.manifest["jobs"][0]["product_layers"][0]["asset_path"] = "cutout.png"
        result = self.inspect()
        self.assertIn("SOURCE_LAYER:0:CUTOUT_SOURCE_BINDING_REQUIRED", result["layer_blockers"])
        self.bind_cutout()
        self.assertEqual([], decide(self.manifest)["blocked_reasons"])

    def test_mask_change_invalidates_cutout_review(self):
        Image.new("L", (400, 400), 200).save(self.base / "mask.png")
        self.manifest["jobs"][0]["product_layers"][0]["mask_path"] = "mask.png"
        self.inspect()
        self.bind_cutout()
        self.assertEqual([], decide(self.manifest)["blocked_reasons"])
        Image.new("L", (400, 400), 100).save(self.base / "mask.png")
        quality.assess_sources(self.manifest, self.base)
        result = decide(self.manifest)
        self.assertIn("SOURCE_LAYER:0:CUTOUT_SOURCE_BINDING_REQUIRED", result["layer_blockers"])
        self.assertIn("SOURCE_ASSESSMENT_CONTEXT_STALE", result["blocked_reasons"])

    def test_actual_crop_target_configuration_is_bound_to_assessment(self):
        self.inspect()
        self.manifest["jobs"][0]["product_layers"][0]["crop_bbox_norm"] = [0.1, 0.1, 0.8, 0.8]
        result = decide(self.manifest)
        self.assertIn("SOURCE_LAYER:0:ASSET_ASSESSMENT_STALE", result["layer_blockers"])
        self.assertIn("SOURCE_ASSESSMENT_CONTEXT_STALE", result["blocked_reasons"])

    def test_small_cutout_cannot_use_large_reference_to_pass_upscale_gate(self):
        Image.new("RGBA", (40, 40), (10, 20, 30, 200)).save(self.base / "tiny.png")
        self.manifest["jobs"][0]["product_layers"][0]["asset_path"] = "tiny.png"
        self.inspect()
        self.bind_cutout()
        self.assertIn("SOURCE_LAYER:0:ACTUAL_UPSCALE_EXCEEDS_LIMIT", decide(self.manifest)["layer_blockers"])

    def test_multiple_components_use_reviewed_individual_views_and_scales(self):
        Image.new("RGB", (400, 400), "blue").save(self.base / "part_a.png")
        Image.new("RGB", (400, 400), "red").save(self.base / "part_b.png")
        self.manifest["references"] = [reference("part_a", role="component_reference", view="part_a_angle"),
                                       reference("part_b", role="component_reference", view="part_b_angle")]
        job = self.manifest["jobs"][0]
        job["source_reference_ids"] = ["part_a", "part_b"]
        job["source_assessment"]["matched_reference_ids"] = ["part_a", "part_b"]
        job["product_layers"] = [{"reference_id": "part_a", "bbox_norm": [0.1, 0.2, 0.3, 0.3], "opaque_rectangle": True},
                                 {"reference_id": "part_b", "bbox_norm": [0.6, 0.2, 0.3, 0.3], "opaque_rectangle": True}]
        result = self.inspect()
        self.assertEqual([], result["blocked_reasons"])
        self.assertEqual("pixel_composite", result["recommended_mode"])

    def test_generated_layer_cannot_claim_original_pixels(self):
        Image.new("RGB", (400, 400), "blue").save(self.base / "master.png")
        master = reference("master")
        self.manifest["references"].append(master)
        job = self.manifest["jobs"][0]
        job["pixel_source_reference_id"] = "master"
        job["product_layers"] = [{"reference_id": "master", "asset_origin": "original", "opaque_rectangle": True}]
        self.inspect()
        real = self.manifest["references"][0]
        master["provenance"] = {"kind": "generated", "qa_verdict": "pass", "source_reference_ids": ["front"],
                                "reviewed_source_hashes": {"front": real["sha256"]}}
        review_job(self.manifest)
        self.assertIn("SOURCE_LAYER:0:ASSET_ORIGIN_CONTRADICTS_REFERENCE", decide(self.manifest)["layer_blockers"])
        job["product_layers"][0]["asset_origin"] = "generated"
        review_job(self.manifest)
        self.assertEqual([], decide(self.manifest)["blocked_reasons"])

    def test_bad_source_binding_schema_is_rejected(self):
        self.manifest["jobs"][0]["product_layers"][0]["source_binding"] = {"reviewed": "yes", "source_reference_hashes": []}
        errors = quality.validate_quality(self.manifest)
        self.assertTrue(any("reviewed must be boolean" in error for error in errors))
        self.assertTrue(any("source_reference_hashes must map" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
