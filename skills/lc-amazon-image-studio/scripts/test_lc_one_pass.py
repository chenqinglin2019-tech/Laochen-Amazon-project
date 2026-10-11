"""Synthetic V8 acceptance tests. No real credentials, accounts or model calls."""
from __future__ import annotations

import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

import lc_image_studio as entry
import lc_one_pass as workflow
from lc_one_pass_design import adopt_templates, compile_design
from lc_one_pass_export import alpha_background, export_job, normalize
from lc_one_pass_io import StudioError, digest, read_json, sha256, write_json

SCRIPTS = Path(__file__).resolve().parent


class OnePassTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        library = self.root / "library"
        library.mkdir()
        write_json(library / "settings.json", {"builtin": {"enabled": False}})
        self.env = patch.dict(os.environ, {"LC_SKIP_AUTH_PASS_FOR_TESTS": "1",
                                          "LC_TEMPLATE_LIBRARY_DIR": str(library),
                                          "LC_LAYOUT_NODE": "/missing/node",
                                          "LC_LAYOUT_CHROMIUM": "/missing/chromium"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.main = self.root / "rgba.png"
        image = Image.new("RGBA", (160, 160), (90, 70, 50, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((25, 25, 135, 135), fill=(255, 255, 255, 255))
        draw.rectangle((60, 60, 90, 90), fill=(250, 250, 250, 0))
        draw.rectangle((30, 30, 40, 40), fill=(40, 80, 120, 128))
        image.save(self.main)
        self.secondary = self.root / "finished.png"
        Image.new("RGB", (160, 160), (180, 200, 220)).save(self.secondary)

    def cli(self, *argv, code=0):
        output = io.StringIO()
        with redirect_stdout(output):
            result = entry.main([str(value) for value in argv])
        self.assertEqual(result, code, output.getvalue())
        return json.loads(output.getvalue())

    def project(self, count=2, a_plus=False, concurrency=16, modern=False):
        target = self.root / ("project-" + str(len(list(self.root.glob("project-*")))))
        args = ["init", "--project-dir", target, "--project-id", "synthetic",
                "--marketplace", "US", "--language", "en", "--listing-count", count,
                "--short-edge", 1600, "--concurrency", concurrency]
        if a_plus:
            args.append("--include-a-plus")
        result = self.cli(*args)
        path = Path(result["manifest"])
        if not modern:
            # The original acceptance cases exercise unchanged historical V8 records.
            manifest = read_json(path)
            for job in manifest["jobs"]:
                for key in ("main_prompt_version", "main_processing_version", "main_foreground_type"):
                    job.pop(key, None)
            write_json(path, manifest)
        self.cli("add-references", "--manifest", path, "--photos", self.secondary)
        manifest = read_json(path)
        inputs = {"product_truth": {"product": "White component",
                                    "geometry_lock": {"locked_structure": ["one visible hole"]},
                                    "material_lock": {"color": "white", "materials": ["confirmed polymer"]},
                                    "scene_scale_lock": {"support_surface": "table"}},
                  "facts": [{"id": "width", "value": "12", "unit": "cm", "source": "user specification"}],
                  "jobs": []}
        for job in manifest["jobs"]:
            if job["kind"] != "main":
                inputs["jobs"].append({"id": job["id"],
                    "design_brief": {"goal": "Explain the product", "scene": "On a real table", "composition": "Product and readable text"},
                    "approved_copy": [{"role": "headline", "text": "Made for your space"},
                                      {"role": "dimension", "text": "12 cm", "fact_ids": ["width"]},
                                      {"role": "step", "text": "1. Place the item"},
                                      {"role": "faq_question", "text": "How does it work?"},
                                      {"role": "faq_answer", "text": "Place it on a stable surface."}]})
        input_path = self.root / "inputs.json"
        write_json(input_path, inputs)
        self.cli("configure", "--manifest", path, "--input", input_path)
        self.cli("plan", "--manifest", path)
        return path

    def reservations(self, path, **kwargs):
        args = ["reserve", "--manifest", path]
        for key, value in kwargs.items():
            args.extend(["--" + key, value])
        return self.cli(*args)["reservations"]

    def complete(self, path):
        reservations = self.reservations(path)
        manifest = read_json(path)
        batch = ["ingest-batch", "--manifest", path]
        for item in reservations:
            job = workflow.find_job(manifest, item["job"])
            artifact = self.main if job["kind"] == "main" else self.secondary
            if job["kind"] == "a_plus":
                artifact = self.root / (job["id"] + ".png")
                Image.new("RGB", tuple(job["canvas"]), "gray").save(artifact)
            batch.extend(["--item", item["job"], item["attempt_id"], artifact])
        self.cli(*batch)
        for item in reservations:
            if workflow.find_job(manifest, item["job"])["kind"] == "main":
                self.cli("main-background-check", "--manifest", path, "--job", item["job"],
                         "--attempt-id", item["attempt_id"], "--verdict", "pass", "--observation",
                         "Transparent exterior and hole; white product and translucent patch preserved.")
        return self.cli("deliver", "--manifest", path)

    def test_seven_listing_images_direct_delivery_and_idempotency(self):
        path = self.project(count=7)
        first = self.complete(path)
        self.assertTrue(first["complete"])
        self.assertEqual(first["image_count"], 7)
        self.assertEqual([item["id"] for item in first["images"]], [job["id"] for job in read_json(path)["jobs"]])
        before = path.read_bytes()
        self.assertEqual(self.cli("deliver", "--manifest", path), first)
        self.assertEqual(path.read_bytes(), before)
        self.cli("plan", "--manifest", path)
        self.assertFalse(self.reservations(path))
        self.assertFalse((path.parent / "review").exists())
        self.assertTrue(all(job["status"] == "ready_to_deliver" for job in read_json(path)["jobs"]))
        self.assertEqual(sum(len(job["generation_attempts"]) for job in read_json(path)["jobs"]), 7)

    def test_thirteen_images_with_six_independent_a_plus_modules(self):
        path = self.project(count=7, a_plus=True)
        result = self.complete(path)
        self.assertTrue(result["complete"])
        self.assertEqual(result["image_count"], 13)
        self.assertEqual(sum(job["kind"] == "a_plus" for job in read_json(path)["jobs"]), 6)

    def test_prompt_has_numeric_steps_faq_and_copy_change_invalidates(self):
        path = self.project()
        manifest = read_json(path)
        job = manifest["jobs"][1]
        prompt = compile_design(manifest, job, path.parent)["prompt"]
        self.assertIn('"12 cm"', prompt)
        self.assertIn('"1. Place the item"', prompt)
        self.assertIn('"How does it work?"', prompt)
        self.assertNotIn("local_overlay", prompt)
        self.assertNotIn("base image", prompt)
        old = job["generation_fingerprint"]
        job["approved_copy"][0]["text"] = "An updated headline"
        write_json(path, manifest)
        reservations = self.reservations(path)
        self.assertNotIn(job["id"], [item["job"] for item in reservations])
        self.cli("plan", "--manifest", path, "--job", job["id"])
        self.assertNotEqual(read_json(path)["jobs"][1]["generation_fingerprint"], old)

    def test_unverified_numbers_and_required_details_block_only_affected_job(self):
        path = self.project()
        manifest = read_json(path)
        manifest["jobs"][1]["approved_copy"][1]["text"] = "99 cm"
        write_json(path, manifest)
        self.cli("plan", "--manifest", path)
        manifest = read_json(path)
        self.assertEqual(manifest["jobs"][1]["status"], "needs_input")
        self.assertEqual(manifest["jobs"][0]["status"], "pending")
        manifest["critical_details"] = [{"priority": "P0", "visibility": {"01_main": "required"}}]
        write_json(path, manifest)
        self.cli("plan", "--manifest", path)
        self.assertIn("REQUIRED_DETAIL_EVIDENCE_MISSING", read_json(path)["jobs"][0]["plan_issues"])

    def test_secondary_is_deliverable_without_main_check(self):
        path = self.project()
        items = self.reservations(path)
        side = items[1]
        self.cli("ingest-batch", "--manifest", path, "--item", side["job"], side["attempt_id"], self.secondary)
        delivery = self.cli("deliver", "--manifest", path)
        self.assertFalse(delivery["complete"])
        self.assertEqual(delivery["image_count"], 1)
        self.assertEqual(delivery["missing_jobs"][0]["id"], "01_main")

    def test_white_product_hole_and_translucent_patch_preserved(self):
        path = self.project(count=1)
        result = self.complete(path)
        with Image.open(result["images"][0]["path"]) as image:
            self.assertEqual(image.mode, "RGB")
            self.assertEqual(image.getpixel((0, 0)), (255, 255, 255))
            self.assertEqual(image.getpixel((750, 750)), (255, 255, 255))
            self.assertEqual(image.getpixel((1100, 1100)), (255, 255, 255))
            red, green, blue = image.getpixel((350, 350))
            self.assertTrue(140 < red < green < blue < 200)
        job = read_json(path)["jobs"][0]
        evidence = job["delivery"]["white_background"]
        self.assertEqual(evidence["final_sha256"], result["images"][0]["sha256"])
        self.assertGreater(evidence["background_pixels"], 0)

    def test_opaque_near_white_and_corner_white_center_gray_are_not_accepted(self):
        for color in ((254, 254, 254), (255, 255, 255)):
            with self.subTest(color=color):
                image = Image.new("RGB", (50, 50), color)
                ImageDraw.Draw(image).rectangle((10, 10, 40, 40), fill=(180, 180, 180))
                with self.assertRaisesRegex(StudioError, "ALPHA_REQUIRED"):
                    alpha_background(image)
        for alpha in (0, 255):
            with self.assertRaisesRegex(StudioError, "FOREGROUND_AND_BACKGROUND_REQUIRED"):
                alpha_background(Image.new("RGBA", (20, 20), (255, 255, 255, alpha)))

    def test_main_has_three_background_repairs_then_partial_delivery(self):
        path = self.project()
        items = self.reservations(path)
        args = ["ingest-batch", "--manifest", path]
        for item in items:
            args.extend(["--item", item["job"], item["attempt_id"], self.secondary])
        self.cli(*args)
        for number in range(1, 4):
            previous = read_json(path)["jobs"][0]
            repair = self.reservations(path)[0]
            self.assertEqual(repair["kind"], "background_repair")
            self.assertEqual(repair["reference_roles"][0], "edit_target")
            self.assertEqual(repair["references"][0], str(path.parent / previous["raw_output"]))
            self.assertTrue(repair["transparent_background"])
            self.assertEqual(read_json(path)["jobs"][0]["background_repairs"], number)
            self.cli("ingest-batch", "--manifest", path, "--item", repair["job"], repair["attempt_id"], self.secondary)
            self.assertEqual(read_json(path)["jobs"][0]["status"], "pending" if number < 3 else "blocked")
        self.assertEqual(read_json(path)["jobs"][0]["status"], "blocked")
        self.cli("plan", "--manifest", path)
        self.assertFalse(self.reservations(path))
        result = self.cli("deliver", "--manifest", path)
        self.assertFalse(result["complete"])
        self.assertEqual(result["image_count"], 1)
        self.assertEqual(result["missing_jobs"][0]["id"], "01_main")
        self.assertEqual(len(read_json(path)["jobs"][0]["generation_attempts"]), 4)

    def test_third_background_repair_can_succeed_after_transient_failures(self):
        path = self.project(count=1)
        first = self.reservations(path)[0]
        self.cli("ingest-batch", "--manifest", path, "--item", first["job"], first["attempt_id"], self.secondary)
        for number in range(1, 4):
            repair = self.reservations(path)[0]
            self.cli("ingest-batch", "--manifest", path, "--failed", repair["job"], repair["attempt_id"], "Known tool failure")
            retry = self.reservations(path)[0]
            self.assertEqual(retry["kind"], "background_repair")
            self.assertEqual(retry["prompt_hash"], repair["prompt_hash"])
            self.assertEqual(read_json(path)["jobs"][0]["background_repairs"], number)
            self.cli("ingest-batch", "--manifest", path, "--item", retry["job"], retry["attempt_id"],
                     self.main if number == 3 else self.secondary)
        self.cli("main-background-check", "--manifest", path, "--job", retry["job"],
                 "--attempt-id", retry["attempt_id"], "--verdict", "pass", "--observation", "Background and holes separated correctly.")
        self.assertTrue(self.cli("deliver", "--manifest", path)["complete"])
        self.cli("plan", "--manifest", path)
        self.assertFalse(self.reservations(path))
        self.assertEqual(read_json(path)["jobs"][0]["background_repairs"], 3)

    def test_manual_background_checks_share_three_repair_limit(self):
        path = self.project(count=1)
        for number in range(4):
            item = self.reservations(path)[0]
            self.assertEqual(item["kind"], "generation" if number == 0 else "background_repair")
            self.cli("ingest-batch", "--manifest", path, "--item", item["job"], item["attempt_id"], self.main)
            self.cli("main-background-check", "--manifest", path, "--job", item["job"],
                     "--attempt-id", item["attempt_id"], "--verdict", "repair", "--observation", "Synthetic background separation needs repair.")
            job = read_json(path)["jobs"][0]
            self.assertEqual(job["background_repairs"], number)
            self.assertEqual(job["status"], "pending" if number < 3 else "blocked")
        self.cli("plan", "--manifest", path)
        self.assertFalse(self.reservations(path))
        self.assertFalse(self.cli("deliver", "--manifest", path)["complete"])

    def test_dispatch_rejects_background_repair_after_three_rounds(self):
        path = self.project(count=1)
        first = self.reservations(path)[0]
        self.cli("ingest-batch", "--manifest", path, "--item", first["job"], first["attempt_id"], self.secondary)
        manifest = read_json(path)
        manifest["jobs"][0]["background_repairs"] = 3
        write_json(path, manifest)
        self.assertFalse(self.reservations(path))
        job = read_json(path)["jobs"][0]
        self.assertEqual(job["status"], "blocked")
        self.assertEqual(job["blocked_reason"], "MAIN_BACKGROUND_REPAIR_LIMIT_REACHED")
        self.assertEqual(len(job["generation_attempts"]), 1)

    def test_background_repair_can_succeed_and_replay_does_not_regenerate(self):
        path = self.project(count=1)
        first = self.reservations(path)[0]
        self.cli("ingest-batch", "--manifest", path, "--item", first["job"], first["attempt_id"], self.secondary)
        repair = self.reservations(path)[0]
        self.cli("ingest-batch", "--manifest", path, "--item", repair["job"], repair["attempt_id"], self.main)
        self.cli("main-background-check", "--manifest", path, "--job", repair["job"],
                 "--attempt-id", repair["attempt_id"], "--verdict", "pass", "--observation", "Background holes and product edges verified.")
        self.assertTrue(self.cli("deliver", "--manifest", path)["complete"])
        self.cli("plan", "--manifest", path)
        self.assertFalse(self.reservations(path))

    def test_duplicate_result_conflict_wrong_job_and_corruption(self):
        path = self.project()
        items = self.reservations(path)
        side = items[1]
        argv = ["ingest-batch", "--manifest", path, "--item", side["job"], side["attempt_id"], self.secondary]
        self.cli(*argv)
        self.assertTrue(self.cli(*argv)["results"][0]["reused"])
        conflict = self.cli(*argv[:-1], self.main, code=2)
        self.assertIn("ATTEMPT_RESULT_CONFLICT", conflict["errors"][0]["error"])
        wrong = self.cli("ingest-batch", "--manifest", path, "--item", items[0]["job"], side["attempt_id"], self.main, code=2)
        self.assertIn("WRONG_JOB", wrong["errors"][0]["error"])
        broken = self.root / "broken.png"
        broken.write_bytes(b"not an image")
        self.cli("ingest-batch", "--manifest", path, "--item", items[0]["job"], items[0]["attempt_id"], broken, code=2)

    def test_file_and_reference_tampering_are_detected(self):
        path = self.project()
        result = self.complete(path)
        final = Path(result["images"][1]["path"])
        final.write_bytes(b"replacement")
        delivery = self.cli("deliver", "--manifest", path)
        self.assertEqual(delivery["image_count"], 1)
        self.assertIn("FINAL_FILE", delivery["missing_jobs"][0]["reason"])
        manifest = read_json(path)
        reference = path.parent / manifest["references"][0]["path"]
        reference.write_bytes(b"changed reference")
        self.assertEqual(self.cli("deliver", "--manifest", path)["image_count"], 0)

    def test_prompt_tampering_prevents_dispatch(self):
        path = self.project(count=1)
        manifest = read_json(path)
        (path.parent / manifest["jobs"][0]["prompt_file"]).write_text("changed", encoding="utf-8")
        result = self.cli("reserve", "--manifest", path)
        self.assertFalse(result["reservations"])
        self.assertIn("BOUND_PROMPT_FILE_CHANGED", result["refusals"][0]["reason"])

    def test_expired_unknown_calls_keep_slot_and_recover_existing_result(self):
        path = self.project(count=1, concurrency=1)
        item = self.reservations(path)[0]
        manifest = read_json(path)
        manifest["jobs"][0]["generation_attempts"][0]["expires_at"] = time.time() - 1
        write_json(path, manifest)
        error = self.cli("ingest-batch", "--manifest", path, "--item", item["job"], item["attempt_id"], self.main, code=2)
        self.assertIn("EXPIRED_ATTEMPT", error["errors"][0]["error"])
        self.assertFalse(self.reservations(path))
        self.assertEqual(read_json(path)["jobs"][0]["status"], "awaiting_result")
        self.cli("recover-attempt", "--manifest", path, "--job", item["job"], "--attempt-id", item["attempt_id"],
                 "--reason", "Tool returned an existing file")
        self.cli("ingest-batch", "--manifest", path, "--item", item["job"], item["attempt_id"], self.main)
        self.assertEqual(len(read_json(path)["jobs"][0]["generation_attempts"]), 1)

    def test_transient_budget_rate_limit_and_free_release(self):
        path = self.project(count=1)
        for _ in range(3):
            item = self.reservations(path)[0]
            self.cli("ingest-batch", "--manifest", path, "--failed", item["job"], item["attempt_id"], "Known tool failure")
        self.assertEqual(read_json(path)["jobs"][0]["status"], "failed")
        self.cli("plan", "--manifest", path)
        self.assertFalse(self.reservations(path))
        self.cli("reset-transient", "--manifest", path, "--job", "01_main", "--reason", "User authorized another retry round")
        item = self.reservations(path)[0]
        self.cli("ingest-batch", "--manifest", path, "--failed", item["job"], item["attempt_id"], "HTTP 429 rate limit")
        self.assertEqual(read_json(path)["jobs"][0]["transient_failures"], 0)
        self.assertFalse(self.reservations(path))
        manifest = read_json(path)
        manifest["jobs"][0]["retry_after"] = 0
        write_json(path, manifest)
        for _ in range(3):
            item = self.reservations(path)[0]
            self.cli("release", "--manifest", path, "--job", item["job"], "--attempt-id", item["attempt_id"], "--reason", "Not submitted")
        self.assertEqual(read_json(path)["jobs"][0]["transient_failures"], 1)

    def test_batch_errors_do_not_undo_other_images(self):
        path = self.project()
        items = self.reservations(path)
        result = self.cli("ingest-batch", "--manifest", path,
            "--item", items[1]["job"], items[1]["attempt_id"], self.secondary,
            "--item", items[0]["job"], "wrong", self.main, code=2)
        self.assertEqual(result["results"][0]["status"], "ready_to_deliver")
        self.assertEqual(self.cli("deliver", "--manifest", path)["image_count"], 1)

    def test_status_is_read_only_and_missing_browsers_do_not_load_old_pipeline(self):
        path = self.project(count=1)
        before = path.read_bytes()
        self.cli("status", "--manifest", path)
        self.assertEqual(path.read_bytes(), before)
        script = ("import json,sys; from lc_image_studio import main; main(sys.argv[1:]); "
                  "assert not set(sys.modules).intersection({'lc_image_pipeline','lc_layout','lc_typography','lc_workflow'})")
        result = subprocess.run([sys.executable, "-B", "-c", script, "plan", "--manifest", str(path)],
                                cwd=SCRIPTS, env=os.environ.copy(), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.cli("verify")["browser_required"])

    def test_two_process_reservations_respect_capacity(self):
        path = self.project(concurrency=1)
        def run():
            result = subprocess.run([sys.executable, "-B", str(SCRIPTS / "lc_image_studio.py"),
                                     "reserve", "--manifest", str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)["reservations"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            waves = list(pool.map(lambda _: run(), range(2)))
        self.assertEqual(sum(len(wave) for wave in waves), 1)

    def test_template_snapshot_survives_cleared_library_and_detects_changed_plate(self):
        path = self.project()
        manifest = read_json(path)
        manifest.pop("template_snapshot")
        from lc_template_library import Library
        library = Library()
        plate_hash = sha256(self.secondary)
        asset = library.asset_path(plate_hash, "png")
        asset.parent.mkdir(parents=True)
        asset.write_bytes(self.secondary.read_bytes())
        write_json(library.index_path, {plate_hash: {"ext": "png"}})
        family = {"id": "test-family", "revision": 1, "tokens": {"palette": {"accent": "#AA4422"}}}
        template = {"id": "test-template", "revision": 1, "family_id": family["id"],
                    "slot_role": "size_or_components", "observed_shape": "square", "recipe": "detail_callouts",
                    "generation": {"lighting": "soft warm light"}, "layout": {}, "assets": {"plate_sha256": plate_hash}}
        rows = [(family, [template], "user", 2)]
        with patch("lc_template_select.candidate_families", return_value=rows), patch("lc_template_select.recommend", return_value={"selected": {"id": family["id"]}}):
            adopt_templates(manifest, path.parent)
        first = compile_design(manifest, manifest["jobs"][1], path.parent)
        with patch("lc_template_select.candidate_families", side_effect=AssertionError("must not reread library")):
            adopt_templates(manifest, path.parent)
        self.assertEqual(compile_design(manifest, manifest["jobs"][1], path.parent), first)
        plate = path.parent / manifest["template_snapshot"]["data"]["assets"][manifest["jobs"][1]["id"]]["path"]
        plate.write_bytes(b"tampered")
        with self.assertRaisesRegex(StudioError, "TEMPLATE_ASSET_CHANGED"):
            compile_design(manifest, manifest["jobs"][1], path.parent)

    def test_auth_is_checked_without_using_real_config(self):
        path = self.project(count=1)
        before = path.read_bytes()
        with patch("lc_auth_pass.check_pass", return_value=(False, "synthetic refusal")):
            self.cli("plan", "--manifest", path, code=2)
            self.cli("reserve", "--manifest", path, code=2)
            self.cli("deliver", "--manifest", path, code=2)
        self.assertEqual(path.read_bytes(), before)

    def test_unknown_policy_rejected_and_historical_argv_forwarded(self):
        old = self.root / "old.json"
        write_json(old, {"workflow_policy": "future"})
        self.assertIn("UNKNOWN_WORKFLOW", self.cli("status", "--manifest", old, code=2)["errors"][0])
        write_json(old, {"project_id": "old"})
        with patch("lc_image_studio.subprocess.run") as run:
            run.return_value.returncode = 19
            self.assertEqual(entry.main(["status", "--manifest", str(old), "--json"]), 19)
            self.assertEqual(run.call_args.args[0], [sys.executable, str(SCRIPTS / "lc_image_pipeline.py"), "status", "--manifest", str(old), "--json"])

    def test_export_only_change_reexports_without_new_model_attempt(self):
        path = self.project()
        self.complete(path)
        before = read_json(path)
        inputs = self.root / "export-input.json"
        write_json(inputs, {"jobs": [{"id": before["jobs"][1]["id"], "export_keywords": ["catalog"]}]})
        self.cli("configure", "--manifest", path, "--input", inputs)
        self.cli("plan", "--manifest", path)
        self.assertTrue(self.cli("deliver", "--manifest", path)["complete"])
        after = read_json(path)
        self.assertEqual(before["jobs"][1]["generation_fingerprint"], after["jobs"][1]["generation_fingerprint"])
        self.assertNotEqual(before["jobs"][1]["delivery"]["sha256"], after["jobs"][1]["delivery"]["sha256"])
        self.assertEqual(len(after["jobs"][1]["generation_attempts"]), 1)
        self.assertFalse(self.reservations(path))

    def test_unknown_call_cannot_be_reopened_by_configuration_or_manual_input_changes(self):
        path = self.project(count=1, concurrency=1)
        item = self.reservations(path)[0]
        self.cli("ingest-batch", "--manifest", path, "--unknown", item["job"], item["attempt_id"], "Submission unknown")
        before = path.read_bytes()
        inputs = self.root / "changed-input.json"
        write_json(inputs, {"jobs": [{"id": "01_main", "design_brief": {"goal": "Changed", "scene": "Product only", "composition": "Centered"}}]})
        self.cli("configure", "--manifest", path, "--input", inputs, code=2)
        self.assertEqual(before, path.read_bytes())
        manifest = read_json(path)
        manifest["jobs"][0]["design_brief"]["goal"] = "Bypass configure"
        write_json(path, manifest)
        self.cli("plan", "--manifest", path)
        self.assertFalse(self.reservations(path))
        job = read_json(path)["jobs"][0]
        self.assertEqual(job["status"], "awaiting_result")
        self.assertEqual(job["active_attempt_id"], item["attempt_id"])

    def test_aspect_failure_cannot_be_reopened_with_unchanged_input(self):
        path = self.project()
        item = self.reservations(path, job="02_size_or_components")[0]
        wrong_ratio = self.root / "wide.png"
        Image.new("RGB", (200, 100), "gray").save(wrong_ratio)
        self.cli("ingest-batch", "--manifest", path, "--item", item["job"], item["attempt_id"], wrong_ratio)
        self.cli("plan", "--manifest", path)
        self.assertFalse(self.reservations(path, job=item["job"]))
        self.assertEqual(read_json(path)["jobs"][1]["status"], "needs_input")
        self.assertEqual(len(read_json(path)["jobs"][1]["generation_attempts"]), 1)

    def test_unknown_call_rejects_new_references_without_losing_recovery(self):
        path = self.project(count=1)
        item = self.reservations(path)[0]
        self.cli("ingest-batch", "--manifest", path, "--unknown", item["job"], item["attempt_id"], "Unknown submission")
        before = path.read_bytes()
        self.cli("add-references", "--manifest", path, "--photos", self.main, code=2)
        self.assertEqual(path.read_bytes(), before)
        self.cli("recover-attempt", "--manifest", path, "--job", item["job"], "--attempt-id", item["attempt_id"],
                 "--reason", "Recovered existing file")
        self.cli("ingest-batch", "--manifest", path, "--item", item["job"], item["attempt_id"], self.main)
        self.assertEqual(read_json(path)["jobs"][0]["status"], "main_background_pending")

    def test_repaired_main_reexports_metadata_and_new_evidence_starts_normal_generation(self):
        path = self.project(count=1)
        first = self.reservations(path)[0]
        self.cli("ingest-batch", "--manifest", path, "--item", first["job"], first["attempt_id"], self.secondary)
        repair = self.reservations(path)[0]
        self.cli("ingest-batch", "--manifest", path, "--item", repair["job"], repair["attempt_id"], self.main)
        self.cli("main-background-check", "--manifest", path, "--job", repair["job"], "--attempt-id", repair["attempt_id"],
                 "--verdict", "pass", "--observation", "Exterior background and holes separated correctly.")
        inputs = self.root / "metadata.json"
        write_json(inputs, {"jobs": [{"id": "01_main", "export_keywords": ["catalog"]}]})
        self.cli("configure", "--manifest", path, "--input", inputs)
        self.cli("plan", "--manifest", path)
        self.assertTrue(self.cli("deliver", "--manifest", path)["complete"])
        self.assertFalse(self.reservations(path))
        self.assertEqual(len(read_json(path)["jobs"][0]["generation_attempts"]), 2)
        self.cli("add-references", "--manifest", path, "--photos", self.main)
        self.cli("plan", "--manifest", path)
        item = self.reservations(path)[0]
        self.assertEqual(item["kind"], "generation")
        self.assertNotIn("edit_target", item["reference_roles"])
        self.assertEqual(read_json(path)["jobs"][0]["background_repairs"], 0)

    def test_units_and_malformed_planning_inputs_do_not_silently_pass(self):
        path = self.project()
        manifest = read_json(path)
        job = manifest["jobs"][1]
        job["approved_copy"][1]["text"] = "12 in"
        with self.assertRaisesRegex(StudioError, "UNIT_MISMATCH"):
            compile_design(manifest, job, path.parent)
        job["approved_copy"][1]["text"] = "12 cm"
        job["source_reference_ids"] = [None]
        with self.assertRaisesRegex(StudioError, "PRODUCT_REFERENCES_REQUIRED"):
            compile_design(manifest, job, path.parent)
        invalid = self.root / "null-manifest.json"
        write_json(invalid, None)
        self.assertIn("MANIFEST_MUST_BE_OBJECT", self.cli("status", "--manifest", invalid, code=2)["errors"][0])

    def test_aspect_mismatch_path_escape_and_state_injection_rejected(self):
        with self.assertRaisesRegex(StudioError, "ASPECT_RATIO_MISMATCH"):
            normalize(Image.new("RGB", (200, 100)), [1600, 1600])
        path = self.project(count=1)
        patch_file = self.root / "unsafe-input.json"
        write_json(patch_file, {"jobs": [{"id": "01_main", "status": "ready_to_deliver"}]})
        self.cli("configure", "--manifest", path, "--input", patch_file, code=2)
        manifest = read_json(path)
        manifest["references"][0]["path"] = "../finished.png"
        with self.assertRaisesRegex(StudioError, "PATH_OUTSIDE_PROJECT"):
            compile_design(manifest, manifest["jobs"][0], path.parent)


if __name__ == "__main__":
    unittest.main()
