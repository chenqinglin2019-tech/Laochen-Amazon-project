"""Main-pipeline integration tests using real offline Chromium typography.

Sources/model outputs are explicit synthetic fixtures. These tests verify stage
invalidation and typography, not photographic product quality or real claims.
"""
from __future__ import annotations
from copy import deepcopy
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from PIL import Image
import lc_assets
import lc_image_pipeline as pipeline
import lc_layout
from pipeline_test_support import (
    create_v3_fixture, prepare_fixture, simulate_secondary_output,
    finish_fixture, bind_output_reviews,
)


class StudioLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        runtime=lc_layout.doctor()
        if not runtime["passed"]:
            raise unittest.SkipTest("Pinned layout runtime unavailable: "+"; ".join(runtime["errors"]))

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.base=Path(self.temp.name).resolve()

    def tearDown(self):
        self.temp.cleanup()

    def make_project(self, canvas=(1600,1600), suffix="case"):
        base=self.base/suffix
        manifest=create_v3_fixture(base,canvas=canvas)
        job=manifest["jobs"][1]
        job["layout"]={"template":"scene","theme":"neutral","headline":"Everyday, elevated","body":"Thoughtful details."}
        prepare_fixture(manifest,base)
        simulate_secondary_output(manifest,base)
        finish_fixture(manifest,base)
        self.assertEqual(job["status"],"qa_passed")
        return base,manifest,job

    def snapshot(self, base, manifest, job):
        return {"fingerprints":deepcopy(pipeline.current_fingerprints(manifest,job,base)),
                "raw":pipeline.sha256_file(base/job["raw_output"]),
                "layout":pipeline.sha256_file(base/"review/layouts"/f"{job['id']}.png"),
                "final":pipeline.sha256_file(base/job["final_output"]),
                "dispatches":sum(j.get("metrics",{}).get("model_dispatches",0) for j in manifest["jobs"]),
                "repairs":sum(j.get("quality_repairs",0) for j in manifest["jobs"])}

    def assert_no_model_work(self, before, after):
        self.assertEqual(before["fingerprints"]["generation"],after["fingerprints"]["generation"])
        self.assertEqual(before["raw"],after["raw"])
        self.assertEqual(before["dispatches"],after["dispatches"])
        self.assertEqual(before["repairs"],after["repairs"])

    def approve_again(self, manifest, base):
        bind_output_reviews(manifest,base)
        report=pipeline.quality_assurance(manifest,base)
        self.assertEqual(report["summary"]["passed"],len(manifest["jobs"]),report)
        pipeline.create_final_contact_sheet(manifest,base)
        self.assertTrue(pipeline.delivery_check(manifest,base)["ready"])

    def test_copy_edit_only_rerenders_layout_for_both_ratios(self):
        for canvas in [(1600,1600),(1600,2080)]:
            with self.subTest(canvas=canvas):
                base,manifest,job=self.make_project(canvas,suffix=str(canvas[1]))
                before=self.snapshot(base,manifest,job)
                geometry=deepcopy(pipeline.generation_geometry(job))
                job["layout"].update(headline="Made for everyday",body="Clear details. Simple living.")
                self.assertEqual(geometry,pipeline.generation_geometry(job))
                pipeline.aspect_safe_postprocess(manifest,base)
                self.assertTrue(job["layout_result"]["passed"],job["layout_result"])
                after=self.snapshot(base,manifest,job)
                self.assert_no_model_work(before,after)
                self.assertNotEqual(before["fingerprints"]["layout"],after["fingerprints"]["layout"])
                self.assertNotEqual(before["layout"],after["layout"])
                self.assertNotEqual(before["final"],after["final"])
                self.assertEqual(job["semantic_qa_results"]["geometry"]["verdict"],"pass")
                self.assertEqual(job["policy_qa_results"],{})
                self.approve_again(manifest,base)

    def test_font_sizes_and_theme_only_rerender(self):
        base,manifest,job=self.make_project()
        for change in [{"font_sizes":{"headline":150,"body":84,"label":72}},{"theme":"warm"}]:
            with self.subTest(change=change):
                before=self.snapshot(base,manifest,job)
                job["layout"].update(change)
                pipeline.aspect_safe_postprocess(manifest,base)
                self.assertTrue(job["layout_result"]["passed"],job["layout_result"])
                after=self.snapshot(base,manifest,job)
                self.assert_no_model_work(before,after)
                self.assertNotEqual(before["layout"],after["layout"])
                self.assertNotEqual(before["final"],after["final"])
        self.approve_again(manifest,base)

    def test_ai_metadata_only_keeps_layout_and_pixels(self):
        base,manifest,job=self.make_project((1600,2080))
        before=self.snapshot(base,manifest,job)
        layout_path=base/"review/layouts"/f"{job['id']}.png"
        layout_mtime=layout_path.stat().st_mtime_ns
        with Image.open(base/job["final_output"]) as im:before_pixels=lc_assets.pixel_hash(im)
        # Exercise the storage branch only; this artificial scene is not provenance evidence.
        job["ai_disclosure"].update(human_source="synthetic",notes="Fixture for synthetic-performer metadata storage only")
        pipeline.aspect_safe_postprocess(manifest,base)
        after=self.snapshot(base,manifest,job)
        self.assert_no_model_work(before,after)
        self.assertEqual(before["fingerprints"]["layout"],after["fingerprints"]["layout"])
        self.assertNotEqual(before["fingerprints"]["export"],after["fingerprints"]["export"])
        self.assertEqual(before["layout"],after["layout"])
        self.assertEqual(layout_mtime,layout_path.stat().st_mtime_ns)
        self.assertNotEqual(before["final"],after["final"])
        with Image.open(base/job["final_output"]) as im:
            self.assertEqual(before_pixels,lc_assets.pixel_hash(im))
            self.assertIn(lc_assets.SYNTHETIC_KEYWORD,lc_assets.xmp_keywords(im))

    def test_overflow_does_not_consume_model_and_shortening_recovers(self):
        base,manifest,job=self.make_project()
        before=self.snapshot(base,manifest,job)
        job["layout"]["headline"]="Beautiful details "*9
        pipeline.aspect_safe_postprocess(manifest,base)
        self.assertEqual(job["status"],"layout_repair_needed")
        self.assertFalse(job["layout_result"]["passed"])
        self.assertTrue(any(c.get("check")=="text_fit" and not c["passed"] for c in job["layout_result"]["checks"]))
        failed=self.snapshot(base,manifest,job)
        self.assert_no_model_work(before,failed)
        self.assertEqual(before["final"],failed["final"])
        job["layout"]["headline"]="Clear details"
        pipeline.aspect_safe_postprocess(manifest,base)
        self.assertTrue(job["layout_result"]["passed"],job["layout_result"])
        self.assertEqual(job["status"],"generated")
        self.assert_no_model_work(before,self.snapshot(base,manifest,job))
        self.approve_again(manifest,base)

    def test_inset_photo_requires_visual_source_binding_and_replacement_review(self):
        base=self.base/"inset-photo"
        manifest=create_v3_fixture(base)
        job=manifest["jobs"][1]
        inset_path=base/"source/inset-photo.png"
        # An actual raster inset from the known source-photo fixture, not a CSS icon.
        with Image.open(base/"source/product_front.png") as source:
            source.crop((940,980,1210,1190)).save(inset_path)
        job["layout"]={"template":"components","theme":"neutral","headline":"Thoughtful details",
                       "body":"A closer look.","items":[{"text":"Port detail","image":"source/inset-photo.png",
                                                              "evidence_refs":["product_front"]}]}
        prepare_fixture(manifest,base)
        simulate_secondary_output(manifest,base)
        pipeline.aspect_safe_postprocess(manifest,base)
        self.assertTrue(job["layout_result"]["passed"],job["layout_result"])
        for current in manifest["jobs"]:
            current["ai_disclosure"]={"human_source":"none","notes":"Base image reviewed only",
                                       "reviewed_image_sha256":current["image_sha256"]}
        pipeline.aspect_safe_postprocess(manifest,base)
        self.assertEqual(job["status"],"export_repair_needed")
        self.assertIn("AI_DISCLOSURE_INSET_REVIEW_REQUIRED"," ".join(job["export_issues"]))
        self.assertFalse((base/job["final_output"]).exists())
        self.assertEqual(len(job["disclosure_extra_images"]),1)
        self.assertEqual(job["disclosure_extra_images"][0]["sha256"],pipeline.sha256_file(inset_path))

        # The synthetic classification deliberately exercises metadata storage;
        # these artificial product fixtures are not evidence of a real performer.
        job["ai_disclosure"].update(human_source="synthetic",notes="All visual layers reviewed for the synthetic-marker test",
                                    reviewed_visual_fingerprint=job["disclosure_visual_fingerprint"])
        pipeline.aspect_safe_postprocess(manifest,base)
        self.assertEqual(job["status"],"generated")
        with Image.open(base/job["final_output"]) as output:
            self.assertIn(lc_assets.SYNTHETIC_KEYWORD,lc_assets.xmp_keywords(output))
        before=self.snapshot(base,manifest,job)
        approved_visual=job["ai_disclosure"]["reviewed_visual_fingerprint"]
        base_image_hash=job["image_sha256"]
        job["layout"]["headline"]="Details made clear"
        pipeline.aspect_safe_postprocess(manifest,base)
        self.assertEqual(job["status"],"generated")
        self.assertEqual(job["disclosure_visual_fingerprint"],approved_visual)
        self.assertEqual(job["ai_disclosure"]["reviewed_visual_fingerprint"],approved_visual)
        after_copy=self.snapshot(base,manifest,job)
        self.assert_no_model_work(before,after_copy)
        self.assertNotEqual(before["layout"],after_copy["layout"])

        # Replace bytes at the same path: path-only provenance/caching must fail.
        with Image.open(base/"source/product_front.png") as source:
            source.crop((360,430,740,690)).save(inset_path)
        job["layout"]["items"][0]["text"]="Finish detail"
        pipeline.aspect_safe_postprocess(manifest,base)
        self.assertEqual(job["status"],"export_repair_needed")
        self.assertEqual(job["image_sha256"],base_image_hash)
        self.assertNotEqual(job["disclosure_visual_fingerprint"],approved_visual)
        self.assertNotEqual(job["ai_disclosure"].get("reviewed_visual_fingerprint"),job["disclosure_visual_fingerprint"])
        self.assertEqual(job["ai_disclosure"]["human_source"],"unknown")
        self.assertIn("AI_DISCLOSURE_INSET_REVIEW_REQUIRED"," ".join(job["export_issues"]))
        replacement=self.snapshot(base,manifest,job)
        self.assert_no_model_work(before,replacement)
        self.assertEqual(after_copy["final"],replacement["final"])
        self.assertNotEqual(after_copy["layout"],replacement["layout"])
        job["ai_disclosure"]={"human_source":"synthetic","notes":"Replacement inset and base both reviewed in the fixture",
                              "reviewed_image_sha256":job["image_sha256"],
                              "reviewed_visual_fingerprint":job["disclosure_visual_fingerprint"]}
        pipeline.aspect_safe_postprocess(manifest,base)
        self.assertEqual(job["status"],"generated")
        self.assert_no_model_work(before,self.snapshot(base,manifest,job))
        self.approve_again(manifest,base)

    def test_protection_failure_can_restore_original_layout_and_preview(self):
        base,manifest,job=self.make_project((1600,2080))
        before=self.snapshot(base,manifest,job)
        original=deepcopy(job["layout"])
        job["layout"]["protected_regions"]=[{"bbox":[.05,.05,.9,.18],"kind":"face"}]
        pipeline.aspect_safe_postprocess(manifest,base)
        self.assertEqual(job["status"],"layout_repair_needed")
        self.assertTrue(any(c.get("check")=="protected_region" and not c["passed"] for c in job["layout_result"]["checks"]))
        job["layout"]=original
        pipeline.aspect_safe_postprocess(manifest,base)
        self.assertTrue(job["layout_result"]["passed"])
        self.assertEqual(job["status"],"generated")
        after=self.snapshot(base,manifest,job)
        self.assert_no_model_work(before,after)
        preview=base/job["layout_result"]["preview_path"]
        with Image.open(preview) as im:self.assertEqual(im.size,(360,468))
        headline=next(b for b in job["layout_result"]["bboxes"] if b["id"]=="headline")
        self.assertLessEqual(headline["line_count"],2)
        self.assertTrue(job["layout_result"]["requires_visual_review"])
        self.approve_again(manifest,base)
        # Optional durable, labelled integration sample for manual 360px inspection.
        destination=os.environ.get("LC_STUDIO_LAYOUT_TEST_OUTPUT")
        if destination:
            target=Path(destination);target.mkdir(parents=True,exist_ok=True)
            shutil.copy2(base/job["final_output"],target/"fixture-layout-portrait.png")
            shutil.copy2(preview,target/"fixture-layout-portrait-360.png")
            pipeline.write_json(target/"fixture-layout-qa.json",job["layout_result"])
            (target/"README.txt").write_text("Synthetic integration fixture. Validates typography, not real product image quality.\n",encoding="utf-8")


if __name__=="__main__":unittest.main()
