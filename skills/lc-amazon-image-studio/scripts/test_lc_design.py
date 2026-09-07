"""Mixed text-route regressions; all generated pixels/reviews are test fixtures."""
import copy
import tempfile
import unittest
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw
import lc_design as d
import lc_image_pipeline as p
import lc_workflow as w
from pipeline_test_support import (MAIN_ID, SECONDARY_ID, NOTE, create_v3_fixture, prepare_fixture,
                                   simulate_secondary_output, ready_fixture)


class DesignHelpersTests(unittest.TestCase):
    def test_modes_have_one_copy_source_and_legacy_support(self):
        local = {"layout": {"headline": "Local title"}}
        native = {"kind": "listing", "render_mode": "reference_generate", "text_mode": "model_native",
                  "copy": {"headline": "In Your Home", "body": "A seasonal accent"}, "layout": {}}
        self.assertEqual(d.resolve_text_mode(local), "local_overlay")
        self.assertTrue(d.needs_local_layout(local))
        self.assertTrue(d.has_marketing_text(native))
        self.assertFalse(d.needs_local_layout(native))
        self.assertEqual(d.validate_design(native), [])
        native["layout"]["headline"] = "Duplicate"
        self.assertTrue(d.validate_design(native))

    def test_local_panels_without_copy_still_render(self):
        job = {"text_mode": "none", "layout": {"version": 3, "panels": [{"image": "one.png"}]}}
        self.assertTrue(d.needs_local_layout(job))
        self.assertFalse(d.has_marketing_text(job))

    def test_v3_group_copy_is_not_invisible_to_claim_checks(self):
        job = {"text_mode": "local_overlay", "layout": {"version": 3, "text_groups": [
            {"id": "hero", "headline": "Style Your Home"}, {"id": "footer", "label": "Shop now"}]}}
        self.assertEqual(len(d.copy_blocks(job)), 2)
        self.assertIn("PROMOTIONAL_COPY_NOT_ALLOWED_IN_DEFAULT_LISTING_LAYOUT", p.claim_issues({"facts": [], "references": []}, job))

    def test_invalid_native_copy_main_and_none_are_rejected(self):
        for job in [
            {"text_mode": "none", "layout": {"headline": "Forbidden"}},
            {"text_mode": "model_native", "copy": None},
            {"text_mode": "model_native", "copy": "not an object"},
            {"text_mode": "model_native", "kind": "main", "copy": {"headline": "Forbidden"}},
            {"text_mode": "local_overlay", "copy": {"headline": "Two sources"}},
        ]:
            with self.subTest(job=job):
                self.assertTrue(d.validate_design(job))

    def test_transcription_must_be_actual_complete_and_bounded(self):
        job = {"text_mode": "model_native", "copy": {"headline": "A Spring Accent"}}
        valid = {"verdict": "pass", "notes": NOTE, "unexpected_text": [], "blocks": [
            {"id": "headline", "text": "A Spring\nAccent", "bbox_norm": [.1, .1, .6, .2]}]}
        self.assertFalse(d.native_text_review_issues(job, valid))
        for change in ("text", "bbox", "unexpected", "empty", "na"):
            review = copy.deepcopy(valid)
            if change == "text": review["blocks"][0]["text"] = "A Sprlng Accent"
            if change == "bbox": review["blocks"][0]["bbox_norm"] = [.9, .1, .6, .2]
            if change == "unexpected": review["unexpected_text"] = ["Amazon's Choice"]
            if change == "empty": review["blocks"] = []
            if change == "na": review["verdict"] = "not_applicable"
            self.assertTrue(d.native_text_review_issues(job, review), change)

    def test_surface_embedded_3d_requires_actual_carrier_and_legibility_review(self):
        job = {"text_mode": "model_native", "copy": {"headline": "A Spring Accent"},
               "embedding_decision": {"kind": "surface_embedded_3d"}}
        review = {"verdict": "pass", "notes": NOTE, "unexpected_text": [], "blocks": [
            {"id": "headline", "text": "A Spring Accent", "bbox_norm": [.1, .1, .6, .2]}],
            "embedding": {"carrier_surface_visible": True, "material_perspective_pass": True,
                          "lighting_contact_pass": True, "readable_original": True, "readable_360": True,
                          "product_label_unchanged": True, "observed_surface": "Visible wooden backdrop",
                          "notes": "Raised lettering follows the surface perspective and raking light."}}
        self.assertFalse(d.native_text_review_issues(job, review))
        review["embedding"]["readable_360"] = False
        self.assertIn("SURFACE_EMBEDDING_REVIEW_FAILED", d.native_text_review_issues(job, review))
        review["embedding"].pop("observed_surface")
        self.assertIn("SURFACE_EMBEDDING_REVIEW_REQUIRED", d.native_text_review_issues(job, review))


class MixedPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lc-mixed-design-")
        self.base = Path(self.temp.name)
        self.m = create_v3_fixture(self.base)

    def tearDown(self):
        self.temp.cleanup()

    @property
    def job(self):
        return self.m["jobs"][1]

    def native(self):
        self.job.update(text_mode="model_native", copy={"headline": "Fixture Accent", "body": "For the test scene"})
        self.job["design_brief"] = {"version": 1, "generation": {"composition": "subject right, warm background"},
                                    "layout": {"headline_tone": "clean bold sans"}, "reference_ids": []}
        prepare_fixture(self.m, self.base)

    def packet(self):
        self.native()
        simulate_secondary_output(self.m, self.base)
        # A test-only known raster; no model and no production verdicts.
        raw = self.base / self.job["raw_output"]
        with Image.open(raw) as opened:
            image = opened.convert("RGB")
        draw = ImageDraw.Draw(image)
        draw.text((100, 80), "Fixture Accent", fill="black")
        draw.text((100, 120), "For the test scene", fill="black")
        image.save(raw)
        self.job["bound_raw_sha256"] = p.sha256_file(raw)
        with patch("lc_layout.render_batch", side_effect=AssertionError("Native posters must not be lettered twice")):
            result = w.review_prepare(self.m, self.base, SECONDARY_ID,
                                      {"raw_product_bbox_norm": self.job["target_product_bbox_norm"],
                                       "detail_output_bbox_norms": self.job["fixture_output_detail_boxes"]})
        return p.read_json(Path(result["packet"]))

    def judgments(self, packet):
        self.assertTrue(self.m["test_fixture"])
        packet = copy.deepcopy(packet)
        for field in ("semantic_qa_results", "policy_qa_results", "detail_qa_results"):
            for key in packet["reviews"][field]:
                packet["reviews"][field][key] = {"verdict": "pass", "notes": NOTE}
        packet["reviews"]["ai_disclosure"] = {"human_source": "none", "notes": NOTE}
        packet["reviews"]["model_text_review"] = {"verdict": "pass", "notes": NOTE, "unexpected_text": [], "blocks": [
            {"id": "headline", "text": "Fixture Accent", "bbox_norm": [.06, .04, .15, .02]},
            {"id": "body", "text": "For the test scene", "bbox_norm": [.06, .07, .2, .02]}]}
        return packet

    def test_native_prompt_integrates_design_and_exact_copy(self):
        self.native()
        prompt = (self.base / self.job["prompt_file"]).read_text()
        self.assertIn("finished photographic poster", prompt)
        self.assertIn("Fixture Accent", prompt)
        self.assertIn("clean bold sans", prompt)
        self.assertNotIn("without added marketing text", prompt)

    def test_no_native_overlay_and_no_false_geometry_approval(self):
        packet = self.packet()
        self.assertIn("model_text_review", packet["reviews"])
        self.assertIn("visual_design", packet["reviews"]["policy_qa_results"])
        self.assertEqual(self.job["layout_result"]["mode"], "model_native_passthrough")
        self.assertFalse(self.job["layout_result"]["geometry_verified"])
        self.assertTrue(p.mobile_preview_required(self.job))
        self.assertFalse((self.base / self.job["final_output"]).exists())

    def test_missing_transcription_cannot_pass_as_no_text(self):
        packet = self.judgments(self.packet())
        packet["reviews"]["model_text_review"]["blocks"] = []
        before = copy.deepcopy(self.m)
        with self.assertRaisesRegex(p.PipelineError, "model-text review"):
            w.review_submit(self.m, self.base, packet)
        self.assertEqual(before, self.m)

    def test_native_review_success_and_failure_repair_route(self):
        packet = self.judgments(self.packet())
        result = w.review_submit(self.m, self.base, packet)
        self.assertEqual(result["status"], "qa_passed")
        self.assertTrue(w.review_submit(self.m, self.base, packet)["idempotent"])
        failed = self.job["model_text_review"]
        failed["verdict"] = "fail"
        failed["blocks"][0]["text"] = "Wrong fixture copy"
        p.quality_assurance(self.m, self.base, [SECONDARY_ID])
        self.assertEqual(self.job["status"], "generation_repair_needed")
        repair = (self.base / "repairs" / f"{SECONDARY_ID}__semantic.txt").read_text()
        self.assertIn("approved typography", repair)
        self.assertNotIn("text-free layout", repair)

    def test_native_copy_or_typography_invalidates_generation_but_local_copy_does_not(self):
        prepare_fixture(self.m, self.base)
        initial = p.current_fingerprints(self.m, self.job, self.base)
        self.job["layout"] = {"headline": "Local title"}
        self.job["generation_geometry_lock"] = {"image_region_norm": [0, 0, 1, 1],
            "product_region_norm": self.job["target_product_bbox_norm"], "text_regions_norm": []}
        before = p.current_fingerprints(self.m, self.job, self.base)
        self.job["layout"]["headline"] = "Changed locally"
        after = p.current_fingerprints(self.m, self.job, self.base)
        self.assertEqual(before["generation"], after["generation"])
        self.assertNotEqual(before["layout"], after["layout"])
        self.job["layout"] = {}
        self.native()
        before = p.current_fingerprints(self.m, self.job, self.base)
        self.job["copy"]["headline"] = "Different Accent"
        changed_copy = p.current_fingerprints(self.m, self.job, self.base)
        self.assertNotEqual(before["generation"], changed_copy["generation"])
        self.job["design_brief"]["layout"]["headline_tone"] = "elegant serif"
        self.assertNotEqual(changed_copy["generation"], p.current_fingerprints(self.m, self.job, self.base)["generation"])

    def test_old_job_has_no_new_prompt_sections_or_global_version_bump(self):
        prepare_fixture(self.m, self.base)
        self.assertEqual(p.PIPELINE_VERSION, "3.0.0")
        before = p.current_fingerprints(self.m, self.job, self.base)["generation"]
        self.job["design_brief"] = {}
        after = p.current_fingerprints(self.m, self.job, self.base)["generation"]
        self.assertEqual(before, after)
        prompt = (self.base / self.job["prompt_file"]).read_text()
        self.assertIn("without added marketing text", prompt)
        self.assertNotIn("Marketing text mode:", prompt)

    def test_unchanged_packet_is_reused_and_stale_copy_rejected(self):
        packet = self.packet()
        path = self.base / "review" / "packets" / f"{SECONDARY_ID}.json"
        before = (p.sha256_file(path), path.stat().st_mtime_ns)
        cached = w.review_prepare(self.m, self.base, SECONDARY_ID)
        self.assertTrue(cached["cached"])
        self.assertEqual(before, (p.sha256_file(path), path.stat().st_mtime_ns))
        self.job["copy"]["headline"] = "A changed brief"
        with self.assertRaisesRegex(p.PipelineError, "STALE_REVIEW_PACKET"):
            w.review_submit(self.m, self.base, self.judgments(packet))

    def test_batch_ready_jobs_include_pending_local_composition(self):
        self.packet()
        result = w.review_prepare_many(self.m, self.base)
        self.assertEqual([item["job"] for item in result["packets"]], [MAIN_ID, SECONDARY_ID])
        self.assertEqual(len(result["skipped"]), 0)

    def test_native_review_prepare_cli_uses_staged_transaction(self):
        packet = self.packet()
        p.write_json(self.base / "project_manifest.json", self.m)
        raw_hash = p.sha256_file(self.base / self.job["raw_output"])
        command = [sys.executable, str(Path(p.__file__)), "review-prepare", "--manifest",
                   str(self.base / "project_manifest.json"), "--jobs", SECONDARY_ID]
        result = subprocess.run(command, capture_output=True, text=True, timeout=40)
        self.assertEqual(result.returncode, 0, result.stderr)
        after = p.read_json(self.base / "project_manifest.json")
        self.assertEqual(after["jobs"][1]["review_request"]["id"], packet["review_id"])
        self.assertEqual(p.sha256_file(self.base / self.job["raw_output"]), raw_hash)
        self.assertNotIn(".lc-stage", result.stdout)

    def panel_job(self):
        self.job["layout"] = {"version": 3, "recipe": "photo_overlay", "panels": [
            {"id": "scene", "image": "source/product_front.png", "evidence_refs": ["product_front"],
             "box": [.1, .1, .8, .8], "fit": "contain", "source_crop": [0, 0, 1, 1],
             "product_bbox_norm": [.2, .1, .6, .8]}]}
        return self.job

    def test_panel_source_must_reference_the_actual_image_not_only_a_fact(self):
        job = self.panel_job()
        good = p.panel_contracts(self.m, job, self.base)
        self.assertFalse(good[0]["errors"])
        job["layout"]["panels"][0]["evidence_refs"] = ["port_count"]
        bad = p.panel_contracts(self.m, job, self.base)
        self.assertIn("PANEL_REGISTERED_IMAGE_REFERENCE_REQUIRED", bad[0]["errors"])

    def test_v3_surface_object_is_not_rejected_by_legacy_enum(self):
        self.job.update(text_mode="local_overlay", layout={"version": 3, "recipe": "photo_overlay",
            "text_surface": {"kind": "gradient", "color": "#ffffff", "opacity": .5, "padding_em": .4},
            "text_groups": [{"id": "hero", "headline": "Fixture Accent", "box": [.05, .05, .8, .2]}]})
        self.assertEqual(p.validate_manifest(self.m, self.base), [])
        self.job["layout"]["text_surface"]["opacity"] = 9
        self.assertTrue(p.validate_manifest(self.m, self.base))

    def test_panel_reviews_require_each_subject_and_bind_crops_and_sources(self):
        job = self.panel_job()
        contracts = p.panel_contracts(self.m, job, self.base)
        reviews = {"scene": {key: {"verdict": "pass", "notes": NOTE}
                             for key in ("provenance", "product_identity", "crop")}}
        self.assertFalse(p.panel_review_issues(contracts, reviews))
        self.assertTrue(p.panel_review_issues(contracts, {}))
        before = p.digest(contracts)
        job["layout"]["panels"][0]["source_crop"] = [.05, .05, .9, .9]
        self.assertNotEqual(before, p.digest(p.panel_contracts(self.m, job, self.base)))

    def test_generated_panel_requires_hash_bound_real_photo_provenance(self):
        job = self.panel_job()
        target = self.base / "source/panel.png"
        with Image.open(self.base / "source/product_front.png") as image:
            image.save(target)
        provenance = {"kind": "generated", "qa_verdict": "pass", "source_reference_ids": ["product_front"],
                      "reviewed_source_hashes": {"product_front": p.sha256_file(self.base / "source/product_front.png")}}
        self.m["references"].append({"id": "generated_panel", "path": "source/panel.png", "provenance": provenance})
        job["layout"]["panels"][0].update(image="source/panel.png", evidence_refs=["generated_panel"])
        self.assertFalse(p.panel_contracts(self.m, job, self.base)[0]["errors"])
        provenance["reviewed_source_hashes"]["product_front"] = "stale"
        self.assertIn("PANEL_SOURCE_BINDING_STALE", p.panel_contracts(self.m, job, self.base)[0]["errors"])

    def test_panel_packet_cannot_submit_without_per_panel_review(self):
        self.panel_job()
        self.job["text_mode"] = "none"
        prepare_fixture(self.m, self.base)
        simulate_secondary_output(self.m, self.base)
        result = w.review_prepare(self.m, self.base, SECONDARY_ID,
                                  {"raw_product_bbox_norm": self.job["target_product_bbox_norm"],
                                   "detail_output_bbox_norms": self.job["fixture_output_detail_boxes"]})
        packet = p.read_json(Path(result["packet"]))
        self.assertEqual(packet["panels"][0]["sources"][0]["id"], "product_front")
        for field in ("semantic_qa_results", "policy_qa_results", "detail_qa_results"):
            for key in packet["reviews"][field]:
                packet["reviews"][field][key] = {"verdict": "pass", "notes": NOTE}
        packet["reviews"]["ai_disclosure"] = {"human_source": "none", "notes": NOTE}
        with self.assertRaisesRegex(p.PipelineError, "panel reviews"):
            w.review_submit(self.m, self.base, packet)
        packet["reviews"]["panel_reviews"] = {"scene": {key: {"verdict": "pass", "notes": NOTE}
                                                         for key in ("provenance", "product_identity", "crop")}}
        result = w.review_submit(self.m, self.base, packet)
        self.assertEqual(result["status"], "qa_passed")
        self.job["layout"]["panels"][0]["source_crop"] = [.05, .05, .9, .9]
        with self.assertRaisesRegex(p.PipelineError, "STALE_REVIEW_PACKET"):
            w.review_submit(self.m, self.base, packet)

    def test_cli_qa_preserves_live_fingerprints_and_delivery(self):
        self.m = ready_fixture(self.base)
        command = [sys.executable, str(Path(p.__file__)), "qa", "--manifest",
                   str(self.base / "project_manifest.json"), "--jobs", SECONDARY_ID]
        result = subprocess.run(command, capture_output=True, text=True, timeout=40)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.m = p.read_json(self.base / "project_manifest.json")
        self.assertEqual(self.job["qa_fingerprint"], p.qa_fingerprint(self.m, self.job, self.base))
        self.assertTrue(p.delivery_check(self.m, self.base)["ready"])

    def test_native_cli_submit_finalize_delivery_has_stable_bindings(self):
        self.m = ready_fixture(self.base)
        packet = self.judgments(self.packet())
        packet_path = self.base / "review" / "fixture-native-submission.json"
        p.write_json(packet_path, packet)
        manifest_path = self.base / "project_manifest.json"
        p.write_json(manifest_path, self.m)
        executable = [sys.executable, str(Path(p.__file__))]
        for arguments in (["review-submit", "--packet", str(packet_path)], ["finalize"], ["delivery-check"]):
            result = subprocess.run(executable + arguments + ["--manifest", str(manifest_path)],
                                    capture_output=True, text=True, timeout=40)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.m = p.read_json(manifest_path)
        self.assertEqual(self.job["qa_fingerprint"], p.qa_fingerprint(self.m, self.job, self.base))
        self.assertEqual(self.job["model_text_review_context"], p.native_text_context(self.m, self.job, self.base))

    def test_init_scaffolds_v3_local_and_never_invents_model_copy(self):
        path = p.init_project(self.base / "new", "new-design", marketplace="US", language="en")
        jobs = p.read_json(path)["jobs"]
        self.assertEqual(jobs[0]["text_mode"], "none")
        self.assertTrue(all(job["text_mode"] == "local_overlay" and job["layout"]["version"] == 3 for job in jobs[1:]))
        self.assertTrue(all("copy" not in job for job in jobs))

    def test_missing_design_reference_cannot_be_approved(self):
        self.packet()
        self.job["design_resolution"] = {"status": "needs_input", "reason": "Missing explicit reference"}
        result = w.review_prepare(self.m, self.base, SECONDARY_ID, force=True)
        packet = self.judgments(p.read_json(Path(result["packet"])))
        with self.assertRaisesRegex(p.PipelineError, "needs_input"):
            w.review_submit(self.m, self.base, packet)

    def test_unresolved_design_invalidates_previously_passed_qa(self):
        packet = self.judgments(self.packet())
        w.review_submit(self.m, self.base, packet)
        self.job["design_resolution"] = {"status": "needs_input"}
        report = p.quality_assurance(self.m, self.base, [SECONDARY_ID], update_overviews=False)
        result = next(item for item in report["jobs"] if item["id"] == SECONDARY_ID)
        self.assertEqual(self.job["status"], "review_pending")
        self.assertIn("design_reference_resolution", result["missing_reviews"])

    def test_required_reference_blocks_plan_transition_and_tool_events(self):
        self.native()
        self.job["design_resolution"] = {"status": "needs_input", "required": True}
        self.m["anchor_job_id"] = SECONDARY_ID
        dispatch = p.execution_plan(self.m)["dispatch"]
        self.assertNotIn(SECONDARY_ID, [item["id"] for item in dispatch])
        self.assertEqual(dispatch[0]["id"], self.m["jobs"][0]["id"])
        with self.assertRaisesRegex(p.PipelineError, "Required design reference"):
            p.transition_job(self.m, SECONDARY_ID, "generating", NOTE, self.base)
        self.job["design_resolution"]["required"] = False
        p.transition_job(self.m, SECONDARY_ID, "generating", NOTE, self.base)
        self.job["design_resolution"]["required"] = True
        with self.assertRaisesRegex(p.PipelineError, "Required design reference"):
            w.attempt_event(self.m, SECONDARY_ID, self.job["active_attempt_id"], "tool_started")
        self.assertNotIn("tool_started_at", self.job["generation_attempts"][-1])

    def test_prepare_blocks_required_missing_reference_without_destroying_existing_raw(self):
        self.packet()
        raw = self.base / self.job["raw_output"]
        before = p.sha256_file(raw)
        self.job["design_resolution"] = {"status": "needs_input", "required": True}
        with patch("lc_style_reference.prepare_design_briefs"):
            p.prepare(self.m, self.base, [SECONDARY_ID])
        self.assertEqual(before, p.sha256_file(raw))
        self.assertEqual(self.job["generated_prompt_hash"], self.job["prompt_hash"])
        self.assertEqual(self.job["status"], "review_pending")
        self.job["status"] = "pending"
        with patch("lc_style_reference.prepare_design_briefs"):
            p.prepare(self.m, self.base, [SECONDARY_ID])
        self.assertEqual(self.job["status"], "blocked")
        self.assertTrue(self.job["blocked_reason"].startswith("DESIGN_REFERENCE_REQUIRED:"))

    def test_four_scene_layers_compose_locally_and_require_each_panel_review(self):
        original = self.m["references"][0]
        original_hash = p.sha256_file(self.base / original["path"])
        slots = [[.01, .2, .48, .38], [.51, .2, .48, .38], [.01, .6, .48, .38], [.51, .6, .48, .38]]
        refs, layers = [], []
        for index, slot in enumerate(slots):
            rid, relative = f"scene_{index}", f"source/scene_{index}.png"
            with Image.open(self.base / original["path"]) as image:
                image.save(self.base / relative)
            ref = copy.deepcopy(original)
            ref.update(id=rid, path=relative, provenance={"kind": "generated", "qa_verdict": "pass",
                "source_reference_ids": [original["id"]], "reviewed_source_hashes": {original["id"]: original_hash}})
            refs.append(ref)
            layers.append({"reference_id": rid, "asset_path": relative, "asset_origin": "generated",
                           "opaque_rectangle": True, "bbox_norm": slot, "crop_bbox_norm": [0, 0, 1, 1]})
        self.m["references"].extend(refs)
        # Optional details still exist in the project census; this test targets composition/source contracts.
        for detail in self.m["critical_details"]:
            detail["visibility"][SECONDARY_ID] = "optional"
        self.job.update(render_mode="pixel_composite", text_mode="none", placement_mode="manual",
            source_reference_ids=[ref["id"] for ref in refs], product_layers=layers,
            target_product_bbox_norm=[.01, .2, .98, .78],
            layout={"version": 3, "recipe": "scene_grid", "panels": [], "text_groups": []},
            source_assessment={"scene_fit": "matched", "degradation": "none", "evidence": "sufficient",
                               "matched_reference_ids": [ref["id"] for ref in refs], "reason": NOTE})
        prepare_fixture(self.m, self.base)
        with patch("lc_layout.render_batch", side_effect=AssertionError("Text-free composed tiles need no second renderer")):
            p.aspect_safe_postprocess(self.m, self.base, job_ids=[SECONDARY_ID], export=False)
        self.assertEqual(self.job["render_mode"], "pixel_composite")
        self.assertEqual(self.job["attempts"], 0)
        self.assertEqual(self.job["metrics"]["local_composites"], 1)
        self.assertEqual(len(self.job["product_layer_provenance"]), 4)
        contracts = p.panel_contracts(self.m, self.job, self.base)
        self.assertEqual([item["id"] for item in contracts], [f"layer-{i}" for i in range(4)])
        self.assertTrue(all(not item["errors"] and item["mapped_product_bbox_norm"] for item in contracts))
        packet_path = w.review_prepare(self.m, self.base, SECONDARY_ID)["packet"]
        packet = p.read_json(Path(packet_path))
        self.assertEqual(set(packet["reviews"]["panel_reviews"]), {f"layer-{i}" for i in range(4)})
        self.assertIn("PANEL_REVIEWS_INCOMPLETE", p.panel_review_issues(contracts, {}))
        raw = self.base / self.job["raw_output"]
        before = (raw.stat().st_mtime_ns, p.sha256_file(raw))
        p.aspect_safe_postprocess(self.m, self.base, job_ids=[SECONDARY_ID], export=False)
        self.assertEqual(before, (raw.stat().st_mtime_ns, p.sha256_file(raw)))
        self.assertEqual(self.job["metrics"]["local_composites"], 1)

    def test_layout_timing_uses_measured_per_job_phases_not_batch_elapsed(self):
        self.job["layout"] = {"headline": "Fixture"}
        prepare_fixture(self.m, self.base)
        simulate_secondary_output(self.m, self.base)
        def fake_render(manifest, base, jobs):
            results = {}
            for job in jobs:
                target = base / "review" / "layouts" / f"{job['id']}.png"
                target.parent.mkdir(parents=True, exist_ok=True)
                with Image.open(base / job["layout_input"]) as image:
                    image.save(target)
                results[job["id"]] = {"passed": True, "output_path": str(target), "checks": [], "runtime": {
                    "python_prepare_seconds": .2, "render_seconds": .3, "preview_seconds": .1,
                    "batch_elapsed_seconds": 30, "batch_id": "fixture-batch"}}
            return results
        with patch("lc_layout.render_batch", side_effect=fake_render):
            p.aspect_safe_postprocess(self.m, self.base, job_ids=[SECONDARY_ID], export=False)
        timings = [item for item in self.job["timings"] if item["stage"] == "layout"]
        self.assertEqual(len(timings), 1)
        self.assertEqual(timings[0]["seconds"], .6)
        self.assertEqual(timings[0]["batch_id"], "fixture-batch")

    def explicit_reference(self):
        path = self.base / "design-reference.png"
        Image.new("RGB", (20, 20), "white").save(path)
        self.job["design_resolution"] = {"status": "selected", "source": "user_reference", "reference": {
            "external_path": str(path), "sha256": p.sha256_file(path)}}
        return path

    def test_changed_explicit_reference_blocks_dispatch_without_changing_generation_hash(self):
        self.native()
        reference = self.explicit_reference()
        generation = p.current_fingerprints(self.m, self.job, self.base)["generation"]
        Image.new("RGB", (20, 20), "red").save(reference)
        self.assertEqual(p.design_reference_issue(self.job), "design_reference_changed")
        self.assertEqual(generation, p.current_fingerprints(self.m, self.job, self.base)["generation"])
        self.assertNotIn(SECONDARY_ID, [item["id"] for item in p.execution_plan(self.m)["dispatch"]])
        with self.assertRaisesRegex(p.PipelineError, "Required design reference"):
            p.transition_job(self.m, SECONDARY_ID, "generating", NOTE, self.base)
        reference.unlink()
        self.assertEqual(p.design_reference_issue(self.job), "design_reference_missing")

    def test_reference_change_after_tool_start_does_not_delay_return_or_ingest(self):
        self.native()
        reference = self.explicit_reference()
        p.transition_job(self.m, SECONDARY_ID, "generating", NOTE, self.base)
        attempt = self.job["active_attempt_id"]
        # A change between dispatch and actual start must still stop the call.
        Image.new("RGB", (20, 20), "red").save(reference)
        with self.assertRaisesRegex(p.PipelineError, "Required design reference"):
            w.attempt_event(self.m, SECONDARY_ID, attempt, "tool_started")
        Image.new("RGB", (20, 20), "white").save(reference)
        w.attempt_event(self.m, SECONDARY_ID, attempt, "tool_started")
        Image.new("RGB", (20, 20), "red").save(reference)
        w.attempt_event(self.m, SECONDARY_ID, attempt, "tool_returned")
        result = w.ingest(self.m, self.base, SECONDARY_ID, self.base / "source/product_front.png", attempt)
        self.assertEqual(result["status"], "generated")
        self.assertEqual(self.job["generation_attempts"][-1]["status"], "ingested")
        self.assertEqual(p.design_reference_issue(self.job), "design_reference_changed")

    def test_changed_explicit_reference_invalidates_qa_without_touching_raw(self):
        self.packet()
        reference = self.explicit_reference()
        with patch("lc_style_reference.prepare_design_briefs"):
            prepared = w.review_prepare(self.m, self.base, SECONDARY_ID, force=True)
        packet = self.judgments(p.read_json(Path(prepared["packet"])))
        self.assertEqual(w.review_submit(self.m, self.base, packet)["status"], "qa_passed")
        raw = self.base / self.job["raw_output"]
        before = (p.sha256_file(raw), self.job["generated_prompt_hash"])
        Image.new("RGB", (20, 20), "red").save(reference)
        report = p.quality_assurance(self.m, self.base, [SECONDARY_ID], update_overviews=False)
        result = next(item for item in report["jobs"] if item["id"] == SECONDARY_ID)
        self.assertEqual(self.job["status"], "review_pending")
        self.assertIn("design_reference_resolution", result["missing_reviews"])
        self.assertEqual(before, (p.sha256_file(raw), self.job["generated_prompt_hash"]))


if __name__ == "__main__":
    unittest.main()
