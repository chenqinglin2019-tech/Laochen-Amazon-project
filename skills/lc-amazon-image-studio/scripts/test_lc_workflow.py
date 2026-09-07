"""Explicit synthetic fixtures for transactional ingestion and real-review boundaries."""
from __future__ import annotations

import copy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import lc_image_pipeline as p
import lc_workflow as w
from pipeline_test_support import (MAIN_ID, SECONDARY_ID, NOTE, create_v3_fixture,
                                   prepare_fixture, simulate_secondary_output, ready_fixture)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lc-workflow-test-")
        self.base = Path(self.temp.name)
        self.m = create_v3_fixture(self.base)
        prepare_fixture(self.m, self.base)

    def tearDown(self):
        self.temp.cleanup()

    def secondary(self):
        return p.find_by_id(self.m["jobs"], SECONDARY_ID)

    def start(self):
        p.transition_job(self.m, SECONDARY_ID, "generating", NOTE, self.base)
        return self.secondary()["active_attempt_id"]

    def artifact(self, color="white"):
        path = self.base / f"fixture-artifact-{color}.png"
        Image.new("RGB", (1600, 1600), color).save(path)
        return path

    def prepare_packet(self):
        simulate_secondary_output(self.m, self.base)
        job = self.secondary()
        result = w.review_prepare(self.m, self.base, SECONDARY_ID,
                                  {"raw_product_bbox_norm": job["target_product_bbox_norm"],
                                   "detail_output_bbox_norms": job["fixture_output_detail_boxes"]})
        return p.read_json(Path(result["packet"]))

    def fixture_judgments(self, packet):
        self.assertTrue(self.m["test_fixture"], "Never infer production verdicts")
        packet = copy.deepcopy(packet)
        for field in ("semantic_qa_results", "policy_qa_results", "detail_qa_results"):
            for key in packet["reviews"][field]:
                packet["reviews"][field][key] = {"verdict": "pass", "notes": NOTE}
        packet["reviews"]["ai_disclosure"] = {"human_source": "none", "notes": NOTE}
        return packet

    def enable_v2(self):
        job = self.secondary()
        job["generation_geometry_lock"] = p.generation_geometry(job)
        job["layout"] = {"version": 2, "template": "scene", "headline": "Fixture detail",
                         "text_group": {"box": [.05, .06, .9, .09]},
                         "mobile_sizes": {"headline": 24}, "text_surface": "transparent"}

    def test_ingest_releases_slot_and_is_idempotent(self):
        attempt = self.start()
        artifact = self.artifact()
        w.attempt_event(self.m, SECONDARY_ID, attempt, "tool_started")
        w.attempt_event(self.m, SECONDARY_ID, attempt, "tool_returned")
        result = w.ingest(self.m, self.base, SECONDARY_ID, artifact, attempt)
        self.assertEqual(result["status"], "generated")
        self.assertEqual(sum(j["status"] == "generating" for j in self.m["jobs"]), 0)
        self.assertEqual(self.secondary()["metrics"]["model_dispatches"], 1)
        before = copy.deepcopy(self.secondary())
        self.assertTrue(w.ingest(self.m, self.base, SECONDARY_ID, artifact, attempt)["idempotent"])
        self.assertEqual(before, self.secondary())
        self.assertEqual({t["stage"] for t in self.secondary()["timings"]}, {"queue", "generation", "ingest", "tool", "handoff"})

    def test_generation_transition_and_ingest_never_load_layout_fonts(self):
        self.secondary()["layout"] = {"headline": "Fixture text"}
        prepare_fixture(self.m, self.base)
        expected = p.current_fingerprints(self.m, self.secondary(), self.base)["generation"]
        with patch("lc_layout.layout_fingerprint", side_effect=RuntimeError("Fixture font runtime unavailable")) as fonts:
            self.assertEqual(p.generation_fingerprint(self.m, self.secondary(), self.base), expected)
            attempt = self.start()
            result = w.ingest(self.m, self.base, SECONDARY_ID, self.artifact(), attempt)
            self.assertEqual(result["status"], "generated")
            self.assertTrue((self.base / self.secondary()["raw_output"]).is_file())
            fonts.assert_not_called()

    def test_batch_review_accepts_only_source_review_export_failures(self):
        simulate_secondary_output(self.m, self.base)
        p.aspect_safe_postprocess(self.m, self.base, job_ids=[SECONDARY_ID])
        self.assertEqual(self.secondary()["status"], "export_repair_needed")
        self.assertTrue(p.is_review_ready(self.secondary()))
        result = w.review_prepare_many(self.m, self.base, [SECONDARY_ID])
        self.assertEqual([item["job"] for item in result["packets"]], [SECONDARY_ID])
        self.secondary().update(status="export_repair_needed", export_issues=["EXPORT_SIZE_MISMATCH"])
        self.assertFalse(p.is_review_ready(self.secondary()))
        self.assertEqual(w.review_prepare_many(self.m, self.base, [SECONDARY_ID])["packets"], [])

    def test_keyed_annotations_accept_project_map_for_single_and_subset(self):
        annotations = {MAIN_ID: {"raw_product_bbox_norm": [.2, .1, .6, .8]},
                       SECONDARY_ID: {"detail_output_bbox_norms": {}}}
        self.assertEqual(w.normalize_annotations(self.m, {MAIN_ID}, annotations), {MAIN_ID: annotations[MAIN_ID]})
        self.assertEqual(w.normalize_annotations(self.m, {MAIN_ID}, annotations, single_job=MAIN_ID),
                         {MAIN_ID: annotations[MAIN_ID]})
        with self.assertRaisesRegex(p.PipelineError, "Unknown annotation job"):
            w.normalize_annotations(self.m, {MAIN_ID}, {**annotations, "typo": {}})

    def test_batch_prepare_composes_pending_local_job_and_isolates_bad_annotations(self):
        simulate_secondary_output(self.m, self.base)
        result = w.review_prepare_many(self.m, self.base, annotations={
            SECONDARY_ID: {"detail_output_bbox_norms": {"unknown-detail": [.1, .1, .1, .1]}}})
        self.assertEqual([item["job"] for item in result["packets"]], [MAIN_ID])
        self.assertEqual([item["job"] for item in result["errors"]], [SECONDARY_ID])
        main = p.find_by_id(self.m["jobs"], MAIN_ID)
        self.assertEqual(main["status"], "review_pending")
        self.assertEqual(main["metrics"]["local_composites"], 1)
        self.assertEqual(self.secondary()["status"], "generated")

    def test_batch_submit_retains_valid_job_when_other_packet_is_invalid(self):
        secondary = self.fixture_judgments(self.prepare_packet())
        main_result = w.review_prepare(self.m, self.base, MAIN_ID)
        main = p.read_json(Path(main_result["packet"]))
        result = w.review_submit_many(self.m, self.base, {MAIN_ID: main, SECONDARY_ID: secondary})
        self.assertEqual([item["job"] for item in result["errors"]], [MAIN_ID])
        self.assertEqual([item["job"] for item in result["results"]], [SECONDARY_ID])
        self.assertEqual(self.secondary()["status"], "qa_passed")
        self.assertEqual(p.find_by_id(self.m["jobs"], MAIN_ID)["status"], "review_pending")
        before = copy.deepcopy(self.m)
        with self.assertRaisesRegex(p.PipelineError, "Unknown review job"):
            w.review_submit_many(self.m, self.base, {SECONDARY_ID: secondary, "typo": {"job": "typo"}})
        self.assertEqual(before, self.m)

    def test_batch_submit_rolls_back_failed_job_pixels_before_next_job(self):
        secondary = self.fixture_judgments(self.prepare_packet())
        main_result = w.review_prepare(self.m, self.base, MAIN_ID)
        main = p.read_json(Path(main_result["packet"]))
        final = self.base / p.find_by_id(self.m["jobs"], MAIN_ID)["final_output"]
        submit = w.review_submit

        def partial_failure(manifest, base, packet):
            if packet["job"] == MAIN_ID:
                final.write_bytes(b"incomplete raster")
                (base / "qa_report.json").write_text("{interrupted", encoding="utf-8")
                raise OSError("Fixture interrupted export")
            return submit(manifest, base, packet)

        with patch.object(w, "review_submit", side_effect=partial_failure):
            result = w.review_submit_many(self.m, self.base, [main, secondary])
        self.assertEqual([item["job"] for item in result["results"]], [SECONDARY_ID])
        self.assertFalse(final.exists())
        report = p.read_json(self.base / "qa_report.json")
        self.assertEqual(p.find_by_id(report["jobs"], SECONDARY_ID)["status"], "qa_passed")

    def test_product_observations_reuse_requires_real_bound_proof_and_new_policy_review(self):
        import lc_layout
        if not lc_layout.doctor()["passed"]:
            self.skipTest("Pinned layout runtime unavailable")
        self.m["review_dependency_version"] = 2
        self.enable_v2()
        p.prepare(self.m, self.base, [SECONDARY_ID])
        first = self.fixture_judgments(self.prepare_packet())
        w.review_submit(self.m, self.base, first)
        job = self.secondary()
        raw_sha = p.sha256_file(self.base / job["raw_output"])
        attempts = copy.deepcopy(job["generation_attempts"])
        job["layout"]["headline"] = "Shorter fixture"
        result = w.review_prepare(self.m, self.base, SECONDARY_ID)
        packet = p.read_json(Path(result["packet"]))
        self.assertIn("reused_reviews", packet)
        self.assertEqual(packet["reviews"]["semantic_qa_results"]["geometry"]["verdict"], "pass")
        self.assertIsNone(packet["reviews"]["semantic_qa_results"]["visual_integrity"]["verdict"])
        self.assertTrue(all(value["verdict"] is None for value in packet["reviews"]["policy_qa_results"].values()))
        self.assertEqual(job["generation_attempts"], attempts)
        self.assertEqual(raw_sha, p.sha256_file(self.base / job["raw_output"]))
        with self.assertRaisesRegex(p.PipelineError, "Explicit verdict"):
            w.review_submit(self.m, self.base, packet)
        proof = self.base / job["product_review_proof"]["path"]
        proof.write_text("{}", encoding="utf-8")
        result = w.review_prepare(self.m, self.base, SECONDARY_ID, force=True)
        packet = p.read_json(Path(result["packet"]))
        self.assertNotIn("reused_reviews", packet)
        self.assertTrue(all(value["verdict"] is None for value in packet["reviews"]["semantic_qa_results"].values()))

    def test_cached_image_recovers_missing_output_box_without_pixel_rewrite(self):
        self.prepare_packet()
        job = self.secondary()
        image = self.base / job["image_output"]
        before = (image.stat().st_mtime_ns, p.sha256_file(image))
        expected = job.pop("output_product_bbox_norm")
        # The historical cache had no output annotation despite a valid raw box.
        packet_path = self.base / "review/packets" / f"{SECONDARY_ID}.json"
        packet = p.read_json(packet_path)
        packet["context"] = w.review_context(self.m, job, self.base)
        packet["missing_annotations"] = ["raw_product_bbox_norm"]
        p.write_json(packet_path, packet)
        job["review_request"].update(context_hash=p.digest(packet["context"]), missing_annotations=packet["missing_annotations"])
        result = w.review_prepare(self.m, self.base, SECONDARY_ID,
                                  {"raw_product_bbox_norm": job["raw_product_bbox_norm"],
                                   "detail_output_bbox_norms": job["detail_output_bbox_norms"]})
        self.assertFalse(result.get("cached", False))
        self.assertNotIn("raw_product_bbox_norm", result["missing_annotations"])
        self.assertEqual(job["output_product_bbox_norm"], expected)
        self.assertEqual(before, (image.stat().st_mtime_ns, p.sha256_file(image)))

    def test_ingest_rejects_old_prompt_and_attempt_before_copy(self):
        attempt = self.start()
        artifact = self.artifact()
        self.secondary()["scene"] = "Changed fixture scene"
        before = copy.deepcopy(self.m)
        with self.assertRaisesRegex(p.PipelineError, "STALE_PROMPT"):
            w.ingest(self.m, self.base, SECONDARY_ID, artifact, attempt)
        self.assertEqual(self.m, before)
        self.assertFalse((self.base / self.secondary()["raw_output"]).exists())
        with self.assertRaisesRegex(p.PipelineError, "STALE_ATTEMPT"):
            w.ingest(self.m, self.base, SECONDARY_ID, artifact, "old-attempt")

    def test_ingest_does_not_overwrite_old_raw_or_reaccept_changed_artifact(self):
        raw = self.base / self.secondary()["raw_output"]
        Image.new("RGB", (1600, 1600), "red").save(raw)
        old_hash = p.sha256_file(raw)
        attempt = self.start()
        w.ingest(self.m, self.base, SECONDARY_ID, self.artifact(), attempt)
        self.assertEqual(p.sha256_file(raw), old_hash)
        self.assertIn("raw/attempts/", self.secondary()["raw_output"])
        self.assertTrue(self.secondary()["generation_attempts"][-1]["tool_duration_unavailable"])
        with self.assertRaisesRegex(p.PipelineError, "INGEST_CONFLICT"):
            w.ingest(self.m, self.base, SECONDARY_ID, self.artifact("blue"), attempt)

    def test_tool_events_are_explicit_ordered_and_immutable(self):
        attempt = self.start()
        with self.assertRaises(p.PipelineError):
            w.attempt_event(self.m, SECONDARY_ID, attempt, "tool_returned")
        a = w.attempt_event(self.m, SECONDARY_ID, attempt, "tool_started")
        self.assertEqual(a, w.attempt_event(self.m, SECONDARY_ID, attempt, "tool_started"))
        with self.assertRaises(p.PipelineError):
            w.attempt_event(self.m, SECONDARY_ID, attempt, "tool_started", a["tool_started_at"] + 1)

    def test_review_prepare_has_no_export_failure_and_never_signs(self):
        packet = self.prepare_packet()
        self.assertEqual(self.secondary()["status"], "review_pending")
        self.assertFalse((self.base / self.secondary()["final_output"]).exists())
        self.assertFalse(packet["missing_annotations"])
        self.assertTrue(packet["comparisons"])
        self.assertTrue(all(v["verdict"] is None for v in packet["reviews"]["semantic_qa_results"].values()))
        before = copy.deepcopy(self.m)
        with self.assertRaisesRegex(p.PipelineError, "Explicit verdict"):
            w.review_submit(self.m, self.base, packet)
        self.assertEqual(before, self.m)

    def test_single_review_submit_binds_coordinates_and_all_judgments(self):
        packet = self.fixture_judgments(self.prepare_packet())
        result = w.review_submit(self.m, self.base, packet)
        self.assertEqual(result["status"], "qa_passed")
        self.assertEqual(self.secondary()["detail_review_context"], w.annotation_fingerprint(self.secondary()))
        self.assertTrue(all(v["verdict"] == "pass" for v in self.secondary()["detail_qa_results"].values()))
        self.assertTrue(w.review_submit(self.m, self.base, packet)["idempotent"])
        self.assertEqual(len([t for t in self.secondary()["timings"] if t["stage"] == "qa"]), 1)

    def test_repeated_submit_rejects_changed_final(self):
        packet = self.fixture_judgments(self.prepare_packet())
        w.review_submit(self.m, self.base, packet)
        Image.new("RGB", (1600, 1600), "blue").save(self.base / self.secondary()["final_output"])
        before = copy.deepcopy(self.m)
        with self.assertRaisesRegex(p.PipelineError, "STALE_SUBMITTED_REVIEW"):
            w.review_submit(self.m, self.base, packet)
        self.assertEqual(before, self.m)

    def test_repeated_submit_rejects_changed_report_and_comparison(self):
        packet = self.fixture_judgments(self.prepare_packet())
        w.review_submit(self.m, self.base, packet)
        report_path = self.base / "qa_report.json"
        report = p.read_json(report_path)
        p.find_by_id(report["jobs"], SECONDARY_ID)["status"] = "review_pending"
        p.write_json(report_path, report)
        with self.assertRaisesRegex(p.PipelineError, "STALE_SUBMITTED_REVIEW"):
            w.review_submit(self.m, self.base, packet)
        Image.new("RGB", (20, 20), "blue").save(self.base / packet["comparisons"][0]["path"])
        with self.assertRaisesRegex(p.PipelineError, "comparison artifact changed"):
            w.review_submit(self.m, self.base, packet)

    def test_repeated_submit_rejects_changed_review_values(self):
        packet = self.fixture_judgments(self.prepare_packet())
        w.review_submit(self.m, self.base, packet)
        self.secondary()["policy_qa_results"]["claims"]["verdict"] = "fail"
        with self.assertRaisesRegex(p.PipelineError, "STALE_SUBMITTED_REVIEW"):
            w.review_submit(self.m, self.base, packet)

    def test_mobile_preview_tampering_rejects_unsigned_and_repeated_submission(self):
        packet = self.fixture_judgments(self.prepare_packet())
        preview = self.base / packet["mobile_preview"]
        self.assertEqual(p.sha256_file(preview), packet["context"]["artifacts"]["mobile"])
        original = preview.read_bytes()
        Image.new("RGB", (360, 360), "blue").save(preview)
        with self.assertRaisesRegex(p.PipelineError, "STALE_REVIEW_PACKET"):
            w.review_submit(self.m, self.base, packet)
        w._atomic_bytes(preview, original)
        self.assertEqual(w.review_submit(self.m, self.base, packet)["status"], "qa_passed")
        Image.new("RGB", (360, 360), "blue").save(preview)
        with self.assertRaisesRegex(p.PipelineError, "STALE_REVIEW_PACKET"):
            w.review_submit(self.m, self.base, packet)

    def test_review_prepare_repairs_and_caches_mobile_preview_without_model_or_layout_work(self):
        packet = self.prepare_packet()
        preview = self.base / packet["mobile_preview"]
        expected_hash = p.sha256_file(preview)
        job = self.secondary()
        raw_hash = p.sha256_file(self.base / job["raw_output"])
        layout = self.base / packet["preview"]
        layout_snapshot = layout.stat().st_mtime_ns, p.sha256_file(layout)
        dispatches = job["metrics"]["model_dispatches"]
        Image.new("RGB", (360, 360), "blue").save(preview)
        w.review_prepare(self.m, self.base, SECONDARY_ID)
        self.assertEqual(expected_hash, p.sha256_file(preview))
        self.assertEqual(layout_snapshot, (layout.stat().st_mtime_ns, p.sha256_file(layout)))
        self.assertEqual(raw_hash, p.sha256_file(self.base / job["raw_output"]))
        self.assertEqual(dispatches, job["metrics"]["model_dispatches"])
        before = preview.stat().st_mtime_ns
        w.review_prepare(self.m, self.base, SECONDARY_ID)
        self.assertEqual(before, preview.stat().st_mtime_ns)
        preview.unlink()
        w.review_prepare(self.m, self.base, SECONDARY_ID)
        self.assertEqual(expected_hash, p.sha256_file(preview))

    def test_mobile_preview_tampering_cannot_be_blessed_by_qa_or_delivery(self):
        packet = self.fixture_judgments(self.prepare_packet())
        w.review_submit(self.m, self.base, packet)
        preview = self.base / packet["mobile_preview"]
        Image.new("RGB", (360, 360), "blue").save(preview)
        with self.assertRaisesRegex(p.PipelineError, "mobile preview is missing or changed"):
            p.delivery_check(self.m, self.base)
        report = p.quality_assurance(self.m, self.base, [SECONDARY_ID])
        result = p.find_by_id(report["jobs"], SECONDARY_ID)
        self.assertEqual(result["status"], "review_pending")
        self.assertFalse(next(c for c in result["checks"] if c["code"] == "MOBILE_PREVIEW_BINDING")["passed"])
        self.assertEqual(self.secondary()["quality_repairs"], 0)

    def test_v2_text_requires_mobile_binding_even_if_legacy_verdicts_are_present(self):
        import lc_layout
        if not lc_layout.doctor()["passed"]:
            self.skipTest("Pinned layout runtime unavailable")
        self.enable_v2()
        p.prepare(self.m, self.base, [SECONDARY_ID])
        packet = self.fixture_judgments(self.prepare_packet())
        w.review_submit(self.m, self.base, packet)
        self.secondary().pop("mobile_preview_binding")
        report = p.quality_assurance(self.m, self.base, [SECONDARY_ID])
        self.assertEqual(p.find_by_id(report["jobs"], SECONDARY_ID)["status"], "review_pending")

    def test_stale_review_rejected_without_mutation(self):
        packet = self.fixture_judgments(self.prepare_packet())
        self.secondary()["detail_output_bbox_norms"]["usb_c_port"] = [.1, .1, .1, .1]
        before = copy.deepcopy(self.m)
        with self.assertRaisesRegex(p.PipelineError, "STALE_REVIEW_PACKET"):
            w.review_submit(self.m, self.base, packet)
        self.assertEqual(before, self.m)

    def test_comparison_tampering_and_incomplete_coordinates_rejected(self):
        packet = self.fixture_judgments(self.prepare_packet())
        comparison = self.base / packet["comparisons"][0]["path"]
        Image.new("RGB", (20, 20), "black").save(comparison)
        with self.assertRaisesRegex(p.PipelineError, "comparison artifact changed"):
            w.review_submit(self.m, self.base, packet)
        result = w.review_prepare(self.m, self.base, SECONDARY_ID, {"detail_output_bbox_norms": {}})
        packet = self.fixture_judgments(p.read_json(Path(result["packet"])))
        self.assertTrue(packet["missing_annotations"])
        with self.assertRaisesRegex(p.PipelineError, "coordinates/evidence"):
            w.review_submit(self.m, self.base, packet)

    def test_actual_failure_is_not_turned_into_pass(self):
        packet = self.fixture_judgments(self.prepare_packet())
        packet["reviews"]["semantic_qa_results"]["components"]["verdict"] = "fail"
        result = w.review_submit(self.m, self.base, packet)
        self.assertEqual(result["status"], "generation_repair_needed")
        self.assertEqual(self.secondary()["quality_repairs"], 0)

    def test_incremental_stages_preserve_unselected_jobs_and_artifacts(self):
        self.m = ready_fixture(self.base)
        main = copy.deepcopy(p.find_by_id(self.m["jobs"], MAIN_ID))
        files = {path: (path.stat().st_mtime_ns, p.sha256_file(path))
                 for path in self.base.rglob("*") if path.is_file() and MAIN_ID in str(path)}
        p.prepare(self.m, self.base, [SECONDARY_ID])
        p.aspect_safe_postprocess(self.m, self.base, job_ids=[SECONDARY_ID])
        p.quality_assurance(self.m, self.base, [SECONDARY_ID])
        self.assertEqual(main, p.find_by_id(self.m["jobs"], MAIN_ID))
        self.assertEqual(files, {path: (path.stat().st_mtime_ns, p.sha256_file(path)) for path in files})
        report = p.read_json(self.base / "qa_report.json")
        self.assertEqual(report["summary"]["passed"], 2)

    def test_contact_sheets_reuse_content_cache(self):
        self.m = ready_fixture(self.base)
        paths = [self.base / "final/contact_sheet.png", self.base / "review/micro_detail_contact_sheet.png"]
        before = [path.stat().st_mtime_ns for path in paths]
        p.quality_assurance(self.m, self.base, [SECONDARY_ID])
        p.create_final_contact_sheet(self.m, self.base)
        self.assertEqual(before, [path.stat().st_mtime_ns for path in paths])

    def test_delivery_rejects_changed_comparison_even_when_summary_is_intact(self):
        self.m = ready_fixture(self.base)
        report = p.read_json(self.base / "qa_report.json")
        comparison = self.base / report["jobs"][0]["details"][0]["comparison_path"]
        Image.new("RGB", (20, 20), "blue").save(comparison)
        with self.assertRaisesRegex(p.PipelineError, "detail comparison missing or changed"):
            p.delivery_check(self.m, self.base)

    def test_source_change_with_scoped_qa_cannot_deliver_unselected_old_pass(self):
        self.m = ready_fixture(self.base)
        old_main = copy.deepcopy(p.find_by_id(self.m["jobs"], MAIN_ID))
        source = self.base / "source/product_front.png"
        with Image.open(source) as image:
            image.putpixel((100, 100), (0, 0, 0))
            image.save(source)
        p.prepare(self.m, self.base, [SECONDARY_ID])
        p.quality_assurance(self.m, self.base, [SECONDARY_ID])
        self.assertEqual(old_main, p.find_by_id(self.m["jobs"], MAIN_ID))
        with self.assertRaisesRegex(p.PipelineError, MAIN_ID):
            p.delivery_check(self.m, self.base)

    def test_style_selection_change_discards_the_old_design_verdict(self):
        job = self.secondary()
        job["generation_geometry_lock"] = p.generation_geometry(job)
        job["layout"] = {"version": 2, "headline": "Fixture headline"}
        self.m["style_reference_selection_path"] = "fixture-style.json"
        p.write_json(self.base / "fixture-style.json", {"primary": "old-fixture"})
        job["policy_qa_results"]["visual_design"] = {"verdict": "pass", "notes": NOTE}
        job["visual_design_review_context"] = p.visual_design_context(self.m, job, self.base)
        job["status"] = "qa_passed"
        p.invalidate_visual_design_review(self.m, job, self.base)
        self.assertIn("visual_design", job["policy_qa_results"])
        p.write_json(self.base / "fixture-style.json", {"primary": "new-fixture"})
        p.invalidate_visual_design_review(self.m, job, self.base)
        self.assertEqual(job["status"], "review_pending")
        self.assertNotIn("visual_design", job["policy_qa_results"])
        self.assertNotIn("visual_design_review_context", job)

    def test_v2_style_change_requires_fresh_review_and_keeps_raw(self):
        import lc_layout
        if not lc_layout.doctor()["passed"]:
            self.skipTest("Pinned layout runtime unavailable")
        self.enable_v2()
        p.prepare(self.m, self.base, [SECONDARY_ID])
        packet = self.fixture_judgments(self.prepare_packet())
        self.assertIn("visual_design", packet["reviews"]["policy_qa_results"])
        self.assertEqual(w.review_submit(self.m, self.base, packet)["status"], "qa_passed")
        job = self.secondary()
        raw_hash = p.sha256_file(self.base / job["raw_output"])
        dispatches = job["metrics"]["model_dispatches"]
        selection_path = self.base / self.m["style_reference_selection_path"]
        selection = p.read_json(selection_path)
        selection["fixture_review_context_note"] = "Changed synthetic style reference context"
        p.write_json(selection_path, selection)
        report = p.quality_assurance(self.m, self.base, [SECONDARY_ID])
        self.assertEqual(p.find_by_id(report["jobs"], SECONDARY_ID)["status"], "review_pending")
        self.assertNotIn("visual_design", job["policy_qa_results"])
        with self.assertRaisesRegex(p.PipelineError, "STALE_REVIEW_PACKET"):
            w.review_submit(self.m, self.base, packet)
        result = w.review_prepare(self.m, self.base, SECONDARY_ID)
        refreshed = self.fixture_judgments(p.read_json(Path(result["packet"])))
        self.assertEqual(w.review_submit(self.m, self.base, refreshed)["status"], "qa_passed")
        self.assertEqual(raw_hash, p.sha256_file(self.base / self.secondary()["raw_output"]))
        self.assertEqual(dispatches, self.secondary()["metrics"]["model_dispatches"])

    def test_missing_style_samples_do_not_block_new_v2_generation(self):
        import lc_style_reference as references
        self.enable_v2()
        self.m["category"] = "home_decor"
        self.secondary()["selling_job"] = "Show the indoor scene and visible details"
        index = p.read_json(references.DEFAULT_INDEX)
        for item in index["references"]:
            item["external_path"] = str(self.base / "missing-style-sample.png")
        index_path = self.base / "fixture-style-index.json"
        p.write_json(index_path, index)
        select = references.prepare_selection
        profile = copy.deepcopy(self.m.get("style_profile"))
        with patch.object(references, "prepare_selection", side_effect=lambda context, path: select(context, path, index_path=index_path)):
            p.prepare(self.m, self.base, [SECONDARY_ID])
        selection = p.read_json(self.base / self.m["style_reference_selection_path"])
        self.assertEqual(selection["selection_status"], "needs_input")
        self.assertTrue(any("MISSING" in reason for reason in selection["needs_input"]), selection)
        self.assertEqual(self.m["generation_gate"]["status"], "open")
        self.assertIn(SECONDARY_ID, [j["id"] for j in p.execution_plan(self.m)["dispatch"]])
        self.assertEqual(profile, self.m.get("style_profile"))

    def test_v2_natural_language_style_selection_is_once_and_revalidated(self):
        import lc_style_reference as references
        index = p.read_json(references.DEFAULT_INDEX)
        if references.verify_external_sources(index):
            self.skipTest("External user sample directory is unavailable")
        self.enable_v2()
        self.m["product_truth"]["product"] = "Black sitting rabbit home decoration with a check bow"
        self.m["category"] = ""
        self.secondary()["selling_job"] = "Show the indoor scene and visible details"
        p.prepare(self.m, self.base, [SECONDARY_ID])
        path = self.base / self.m["style_reference_selection_path"]
        selection = p.read_json(path)
        self.assertEqual(selection["selection_status"], "selected", selection)
        before = path.stat().st_mtime_ns, path.read_bytes()
        p.prepare(self.m, self.base, [SECONDARY_ID])
        self.assertEqual(before, (path.stat().st_mtime_ns, path.read_bytes()))
        selection["primary"]["external_path"] = str(self.base / "missing-selected-reference.png")
        p.write_json(path, selection)
        p.prepare(self.m, self.base, [SECONDARY_ID])
        self.assertEqual(p.read_json(path)["selection_status"], "needs_input")
        self.assertEqual(self.m["generation_gate"]["status"], "open")

    def test_geometry_lock_preserves_generation_and_is_validated(self):
        job = self.secondary()
        old = p.current_fingerprints(self.m, job, self.base)["generation"]
        job["generation_geometry_lock"] = p.generation_geometry(job)
        job["layout"] = {"template": "split", "headline": "Fixture headline"}
        p.prepare(self.m, self.base, [SECONDARY_ID])
        self.assertEqual(old, p.current_fingerprints(self.m, job, self.base)["generation"])
        job["generation_geometry_lock"]["product_region_norm"] = [0, 0, 3, 1]
        self.assertTrue(p.validate_manifest(self.m, self.base))
        with self.assertRaises(p.PipelineError):
            p.generation_geometry(job)

    def test_hold_never_enters_model_queue(self):
        job = self.secondary()
        job["hold"] = True
        self.assertNotIn(SECONDARY_ID, [j["id"] for j in p.execution_plan(self.m)["dispatch"]])
        with self.assertRaisesRegex(p.PipelineError, "HOLD"):
            self.start()

    def test_faq_is_text_requires_facts_and_invalidates_review(self):
        job = self.secondary()
        job["generation_geometry_lock"] = p.generation_geometry(job)
        job["layout"] = {"version": 2, "faq": [{"question": "Size?", "answer": "20 cm"}]}
        self.assertTrue(p.has_text(job))
        self.assertIn("NUMERIC_COPY_REQUIRES_FACT_BINDING", p.claim_issues(self.m, job))
        self.assertIn("visual_design", w.policy_keys(job))
        before = p.qa_fingerprint(self.m, job, self.base)
        job["layout"]["faq"][0]["answer"] = "Indoor display"
        self.assertNotEqual(before, p.qa_fingerprint(self.m, job, self.base))

    def test_cli_ingest_and_unknown_scope_are_atomic(self):
        attempt = self.start()
        manifest = self.base / "project_manifest.json"
        p.write_json(manifest, self.m)
        command = [sys.executable, str(p.SCRIPT_DIR / "lc_image_pipeline.py"), "ingest", "--manifest", str(manifest),
                   "--job", SECONDARY_ID, "--attempt-id", attempt, "--artifact", str(self.artifact())]
        result = subprocess.run(command, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        stored = p.read_json(manifest)
        self.assertEqual(p.find_by_id(stored["jobs"], SECONDARY_ID)["status"], "generated")
        before = manifest.read_bytes()
        result = subprocess.run([sys.executable, str(p.SCRIPT_DIR / "lc_image_pipeline.py"), "prepare",
                                 "--manifest", str(manifest), "--jobs", "missing_job"], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(before, manifest.read_bytes())

    def test_manifest_lock_serializes_independent_processes(self):
        target = self.base / "counter.json"
        p.write_json(target, {"value": 0})
        code = """import sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import lc_image_pipeline as p
from lc_workflow import manifest_lock
path=Path(sys.argv[2])
with manifest_lock(path):
    data=p.read_json(path)
    time.sleep(.15)
    data['value']+=1
    p.write_json(path,data)
"""
        commands = [[sys.executable, "-c", code, str(p.SCRIPT_DIR), str(target)] for _ in range(2)]
        processes = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for command in commands]
        for process in processes:
            output, errors = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, errors.decode())
        self.assertEqual(p.read_json(target), {"value": 2})


if __name__ == "__main__":
    unittest.main()
