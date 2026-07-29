#!/usr/bin/env python3

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw


MODULE_PATH = Path(__file__).with_name("lc_image_pipeline.py")
SPEC = importlib.util.spec_from_file_location("lc_image_pipeline", MODULE_PATH)
assert SPEC and SPEC.loader
PIPELINE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PIPELINE)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        for directory in ("source", "raw", "final"):
            (self.base / directory).mkdir()

        image = Image.new("RGB", (1600, 1600), "#ffffff")
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((320, 160, 1280, 1440), radius=90, fill="#f9f9f9", outline="#333333", width=12)
        draw.rounded_rectangle((992, 1050, 1088, 1088), radius=12, fill="#111111")
        image.save(self.base / "source" / "product_front.png")
        image.save(self.base / "raw" / "01_main.png")
        image.save(self.base / "raw" / "02_back_view.png")

        self.manifest = {
            "schema_version": 2,
            "project_id": "usb-detail-test",
            "run_mode": "risk_gated_auto",
            "generation_backend": "built_in_image_gen",
            "concurrency": 2,
            "critical_detail_census_completed": True,
            "max_transient_retries": 2,
            "max_quality_repairs": 1,
            "product_truth": {
                "product": "USB-powered test product",
                "source_quality": "unknown",
                "safe_upscale_ratio": 1.25,
                "max_marginal_upscale_ratio": 1.75,
                "master_asset_mode": "original_pixels",
                "master_confirmed": False,
                "geometry_lock": {"locked_structure": ["rounded rectangular body"]},
                "material_lock": {"materials": ["white plastic"]},
                "scene_scale_lock": {"physical_dimensions": "confirmed test dimensions"},
            },
            "references": [
                {
                    "id": "product_front",
                    "path": "source/product_front.png",
                    "role": "whole_product_reference",
                    "view": "front",
                    "visual_quality": "sufficient",
                    "product_bbox_norm": [0.2, 0.1, 0.6, 0.8],
                }
            ],
            "critical_details": [
                {
                    "id": "usb_c_port",
                    "name": "USB-C charging port",
                    "priority": "P0",
                    "status": "unknown",
                    "evidence_level": "visual_confirmed",
                    "visual_confirmation": "confirmed",
                    "component": "front-right body edge",
                    "description": "one recessed USB-C opening",
                    "shape": "horizontal rounded rectangle",
                    "orientation": "horizontal",
                    "color": "dark opening in white shell",
                    "locations": [
                        {
                            "reference_id": "product_front",
                            "view": "front",
                            "bbox_in_product_norm": [0.7, 0.695, 0.1, 0.03],
                            "position_description": "front-right edge of the product body",
                        }
                    ],
                    "visibility": {"01_main": "required", "02_back_view": "hidden"},
                }
            ],
            "jobs": [
                self.job("01_main", "main", "front", "pixel_composite", "01_main.png"),
                self.job("02_back_view", "listing", "front", "reference_generate", "02_back_view.png"),
            ],
        }
        self.path = self.base / "project_manifest.json"
        PIPELINE.write_json(self.path, self.manifest)

    def tearDown(self):
        self.temp.cleanup()

    def job(self, job_id, kind, view, render_mode, filename):
        return {
            "id": job_id,
            "required": True,
            "kind": kind,
            "view": view,
            "selling_job": "preserve the exact product",
            "render_mode": render_mode,
            "requires_fine_detail": False,
            "canvas": [1600, 1600],
            "source_reference_ids": ["product_front"],
            "target_product_bbox_norm": [0.2, 0.1, 0.6, 0.8],
            "raw_product_bbox_norm": [0.2, 0.1, 0.6, 0.8],
            "output_product_bbox_norm": [0.2, 0.1, 0.6, 0.8],
            "detail_output_bbox_norms": {},
            "scene": "white test background",
            "composition": "centered",
            "lighting": "neutral",
            "padding_color": "#ffffff",
            "raw_output": f"raw/{filename}",
            "final_output": f"final/{filename}",
            "text_overlays": [],
            "status": "pending",
            "attempts": 0,
            "quality_repairs": 0,
            "semantic_qa_results": {},
            "policy_qa_results": {},
            "detail_qa_results": {},
        }

    def mark_reviews(self, job):
        job["semantic_qa_results"] = {
            "geometry": {"verdict": "pass"},
            "material": {"verdict": "pass"},
            "components": {"verdict": "pass"},
            "scene_scale": {
                "verdict": "not_applicable" if job["kind"] == "main" else "pass"
            },
        }
        job["policy_qa_results"] = {
            "main_product_only": {
                "verdict": "pass" if job["kind"] == "main" else "not_applicable"
            },
            "claims": {"verdict": "pass"},
            "competitor_copy": {"verdict": "pass"},
            "text_readability": {"verdict": "not_applicable"},
        }

    def generate_and_postprocess(self):
        for job in self.manifest["jobs"]:
            PIPELINE.transition_job(self.manifest, job["id"], "generating", None)
            PIPELINE.transition_job(self.manifest, job["id"], "generated", None)
        PIPELINE.aspect_safe_postprocess(self.manifest, self.base)
        for job in self.manifest["jobs"]:
            self.mark_reviews(job)

    def test_prepare_extracts_detail_and_compiles_view_specific_prompt(self):
        PIPELINE.prepare(self.manifest, self.base)
        detail = self.manifest["critical_details"][0]
        self.assertEqual(detail["status"], "confirmed")
        self.assertTrue((self.base / detail["reference_crops"][0]["path"]).is_file())
        main = self.manifest["jobs"][0]
        back = self.manifest["jobs"][1]
        self.assertEqual(main["required_details"], ["usb_c_port"])
        self.assertEqual(back["hidden_details"], ["usb_c_port"])
        prompt = (self.base / main["prompt_file"]).read_text()
        self.assertIn("Critical Detail Lock", prompt)
        self.assertIn("Do not delete, fill, move", prompt)
        back_prompt = (self.base / back["prompt_file"]).read_text()
        self.assertIn("Do not reveal it, relocate it", back_prompt)

    def test_qa_requires_explicit_p0_verdict_and_creates_repair_prompt(self):
        PIPELINE.prepare(self.manifest, self.base)
        self.generate_and_postprocess()
        report = PIPELINE.quality_assurance(self.manifest, self.base)
        self.assertEqual(self.manifest["jobs"][0]["status"], "repair_needed")
        self.assertEqual(report["summary"]["repair_needed"], 1)

        self.manifest["jobs"][0]["detail_qa_results"] = {
            "usb_c_port": {"verdict": "fail", "notes": "port missing"}
        }
        report = PIPELINE.quality_assurance(self.manifest, self.base)
        detail_result = report["jobs"][0]["details"][0]
        self.assertEqual(detail_result["verdict"], "fail")
        self.assertTrue((self.base / detail_result["repair_prompt"]).is_file())

        self.manifest["jobs"][0]["detail_qa_results"] = {
            "usb_c_port": {"verdict": "pass", "notes": "confirmed"}
        }
        report = PIPELINE.quality_assurance(self.manifest, self.base)
        self.assertEqual(self.manifest["jobs"][0]["status"], "qa_passed")
        self.assertTrue((self.base / "review" / "micro_detail_contact_sheet.png").is_file())
        self.assertGreaterEqual(report["summary"]["passed"], 1)

    def test_unverifiable_p0_detail_blocks_required_job(self):
        location = self.manifest["critical_details"][0]["locations"][0]
        location["bbox_in_product_norm"] = [0.7, 0.7, 0.01, 0.005]
        PIPELINE.prepare(self.manifest, self.base)
        self.assertEqual(self.manifest["critical_details"][0]["status"], "unverifiable")
        self.assertEqual(self.manifest["jobs"][0]["status"], "blocked")
        self.assertIn("DETAIL_VIEW_UNVERIFIABLE", self.manifest["jobs"][0]["blocked_reason"])

    def test_prompt_hash_preserves_or_invalidates_cached_pass(self):
        PIPELINE.prepare(self.manifest, self.base)
        main = self.manifest["jobs"][0]
        original_hash = main["prompt_hash"]
        main["status"] = "qa_passed"
        PIPELINE.compile_prompts(self.manifest, self.base)
        self.assertEqual(main["status"], "qa_passed")
        self.assertEqual(main["prompt_hash"], original_hash)
        main["selling_job"] = "changed selling job"
        PIPELINE.compile_prompts(self.manifest, self.base)
        self.assertEqual(main["status"], "pending")
        self.assertNotEqual(main["prompt_hash"], original_hash)

    def test_postprocess_transforms_raw_product_bbox_after_padding(self):
        PIPELINE.prepare(self.manifest, self.base)
        wide = Image.new("RGB", (1600, 800), "white")
        wide.save(self.base / "raw" / "wide.png")
        job = self.manifest["jobs"][0]
        job["raw_output"] = "raw/wide.png"
        job["raw_product_bbox_norm"] = [0.25, 0.25, 0.5, 0.5]
        for current in self.manifest["jobs"]:
            PIPELINE.transition_job(self.manifest, current["id"], "generating", None)
            PIPELINE.transition_job(self.manifest, current["id"], "generated", None)
        PIPELINE.aspect_safe_postprocess(self.manifest, self.base, force=True)
        actual = job["output_product_bbox_norm"]
        expected = [0.25, 0.375, 0.5, 0.25]
        for value, target in zip(actual, expected):
            self.assertAlmostEqual(value, target, places=6)

    def test_retry_and_quality_repair_limits(self):
        PIPELINE.prepare(self.manifest, self.base)
        job = self.manifest["jobs"][0]
        for expected_attempt in (1, 2, 3):
            PIPELINE.transition_job(self.manifest, "01_main", "generating", None)
            self.assertEqual(job["attempts"], expected_attempt)
            PIPELINE.transition_job(self.manifest, "01_main", "pending", None)
        PIPELINE.transition_job(self.manifest, "01_main", "generating", None)
        self.assertEqual(job["status"], "failed")

        job["status"] = "repair_needed"
        PIPELINE.transition_job(self.manifest, "01_main", "generating", None)
        self.assertEqual(job["quality_repairs"], 1)
        job["status"] = "repair_needed"
        PIPELINE.transition_job(self.manifest, "01_main", "generating", None)
        self.assertEqual(job["status"], "blocked")

    def test_p0_visibility_must_cover_every_job(self):
        del self.manifest["critical_details"][0]["visibility"]["02_back_view"]
        errors = PIPELINE.validate_manifest(self.manifest, self.base)
        self.assertTrue(any("explicitly cover every job" in error for error in errors))

    def test_output_paths_cannot_escape_project(self):
        self.manifest["jobs"][0]["final_output"] = "../escaped.png"
        errors = PIPELINE.validate_manifest(self.manifest, self.base)
        self.assertTrue(any("project-relative path" in error for error in errors))

    def test_user_claim_only_detail_without_location_closes_generation_gate(self):
        detail = self.manifest["critical_details"][0]
        detail["locations"] = []
        detail["evidence_level"] = "user_claim_only"
        detail["visual_confirmation"] = "unknown"
        PIPELINE.prepare(self.manifest, self.base)
        self.assertEqual(detail["status"], "unverifiable")
        self.assertEqual(self.manifest["jobs"][0]["status"], "blocked")
        self.assertEqual(self.manifest["generation_gate"]["status"], "closed")
        with self.assertRaisesRegex(PIPELINE.PipelineError, "Generation gate is closed"):
            PIPELINE.transition_job(self.manifest, "02_back_view", "generating", None)

    def test_visual_confirmation_is_required_even_for_large_crop(self):
        detail = self.manifest["critical_details"][0]
        detail["visual_confirmation"] = "unknown"
        PIPELINE.prepare(self.manifest, self.base)
        crop = detail["reference_crops"][0]
        self.assertTrue(crop["pixel_verifiable"])
        self.assertFalse(crop["verifiable"])
        self.assertEqual(detail["status"], "unverifiable")

    def test_detail_crop_names_are_unique_across_references(self):
        duplicate = self.base / "source" / "product_front_2.png"
        with Image.open(self.base / "source" / "product_front.png") as opened:
            opened.save(duplicate)
        self.manifest["references"].append(
            {
                "id": "product_front_2",
                "path": "source/product_front_2.png",
                "role": "secondary_whole_product_reference",
                "view": "front",
                "visual_quality": "sufficient",
                "product_bbox_norm": [0.2, 0.1, 0.6, 0.8],
            }
        )
        second_location = dict(self.manifest["critical_details"][0]["locations"][0])
        second_location["reference_id"] = "product_front_2"
        self.manifest["critical_details"][0]["locations"].append(second_location)
        self.manifest["jobs"][0]["source_reference_ids"].append("product_front_2")
        PIPELINE.prepare(self.manifest, self.base)
        crops = self.manifest["critical_details"][0]["reference_crops"]
        self.assertEqual(len({crop["path"] for crop in crops}), 2)
        prompt = (self.base / self.manifest["jobs"][0]["prompt_file"]).read_text()
        self.assertIn("secondary_whole_product_reference", prompt)

    def test_blocked_job_cannot_be_overwritten_by_qa(self):
        PIPELINE.prepare(self.manifest, self.base)
        main = self.manifest["jobs"][0]
        main["status"] = "blocked"
        main["blocked_reason"] = "MANUAL_BLOCK"
        report = PIPELINE.quality_assurance(self.manifest, self.base)
        self.assertEqual(main["status"], "blocked")
        self.assertEqual(report["jobs"][0]["blocked_reason"], "MANUAL_BLOCK")

    def test_modified_output_fails_current_prompt_binding(self):
        PIPELINE.prepare(self.manifest, self.base)
        self.generate_and_postprocess()
        final_path = self.base / self.manifest["jobs"][0]["final_output"]
        with Image.open(final_path) as opened:
            changed = opened.convert("RGB")
        changed.putpixel((0, 0), (1, 2, 3))
        changed.save(final_path)
        report = PIPELINE.quality_assurance(self.manifest, self.base)
        self.assertEqual(self.manifest["jobs"][0]["status"], "failed")
        self.assertEqual(report["jobs"][0]["checks"][0]["code"], "OUTPUT_BOUND_TO_CURRENT_PROMPT")

    def test_listing_canvas_must_be_1600_square(self):
        self.manifest["jobs"][1]["canvas"] = [1200, 1200]
        errors = PIPELINE.validate_manifest(self.manifest, self.base)
        self.assertTrue(any("[1600, 1600]" in error for error in errors))

    def test_actual_output_scale_can_hard_block_pixel_composite(self):
        self.manifest["product_truth"]["max_marginal_upscale_ratio"] = 1.5
        PIPELINE.prepare(self.manifest, self.base)
        main = self.manifest["jobs"][0]
        main["raw_product_bbox_norm"] = [0.0, 0.0, 1.0, 1.0]
        self.generate_and_postprocess()
        main["detail_qa_results"] = {"usb_c_port": {"verdict": "pass"}}
        report = PIPELINE.quality_assurance(self.manifest, self.base)
        self.assertEqual(main["status"], "blocked")
        scale_check = next(
            check for check in report["jobs"][0]["checks"] if check["code"] == "ACTUAL_SAFE_UPSCALE"
        )
        self.assertFalse(scale_check["passed"])

    def test_delivery_gate_requires_and_verifies_all_artifacts(self):
        PIPELINE.prepare(self.manifest, self.base)
        with self.assertRaisesRegex(PIPELINE.PipelineError, "Delivery gate failed"):
            PIPELINE.delivery_check(self.manifest, self.base)

        self.generate_and_postprocess()
        self.manifest["jobs"][0]["detail_qa_results"] = {
            "usb_c_port": {"verdict": "pass"}
        }
        PIPELINE.quality_assurance(self.manifest, self.base)
        PIPELINE.create_final_contact_sheet(self.manifest, self.base)
        report = PIPELINE.delivery_check(self.manifest, self.base)
        self.assertTrue(report["ready"])


if __name__ == "__main__":
    unittest.main()
