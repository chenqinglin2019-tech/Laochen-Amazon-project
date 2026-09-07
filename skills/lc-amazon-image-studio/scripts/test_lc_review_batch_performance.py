"""No-model batching/ROI regressions. Raster fixtures never approve products."""
from __future__ import annotations

import copy
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

import lc_image_pipeline as p
import lc_layout as layout
import lc_typography as typography
import lc_workflow as workflow
from pipeline_test_support import MAIN_ID, NOTE, create_v3_fixture, prepare_fixture


def full_canvas_contrast(image, background, mask, bboxes):
    """Frozen pre-optimization calculation, including its exact float32 math."""
    fg, bg = typography.luminance(image), typography.luminance(background)
    core = np.asarray(mask.convert("L")) >= 245
    checks = []
    for item in bboxes:
        if item.get("kind") != "text":
            continue
        box = item["bbox"]
        x, y = max(0, math.floor(box["x"])), max(0, math.floor(box["y"]))
        r = min(image.width, math.ceil(box["x"] + box["width"]))
        b = min(image.height, math.ceil(box["y"] + box["height"]))
        selected = core[y:b, x:r]
        a, z = fg[y:b, x:r][selected], bg[y:b, x:r][selected]
        ratios = (np.maximum(a, z) + .05) / (np.minimum(a, z) + .05)
        minimum = float(ratios.min()) if ratios.size else 0
        checks.append({"check": "glyph_contrast", "element": item["id"], "passed": minimum >= 4.5,
            "ratio_min": round(minimum, 4),
            "ratio_p05": round(float(np.quantile(ratios, .05)), 4) if ratios.size else 0,
            "minimum": 4.5, "core_pixels": int(ratios.size),
            "method": "actual raster glyph core alpha >=245 against rendered text-free background"})
    return checks


class ContrastRegionTests(unittest.TestCase):
    def test_random_colors_multibox_and_edge_cases_match_all_core_pixels(self):
        rng = np.random.default_rng(29)
        for size in ((91, 73), (120, 45), (65, 143)):
            width, height = size
            foreground = Image.fromarray(rng.integers(0, 256, (height, width, 3), dtype=np.uint8))
            background = Image.fromarray(rng.integers(0, 256, (height, width, 3), dtype=np.uint8))
            mask = Image.fromarray(rng.integers(240, 256, (height, width), dtype=np.uint8))
            boxes = [{"id": str(i), "kind": "text", "bbox": {"x": x, "y": y, "width": w, "height": h}}
                for i, (x, y, w, h) in enumerate(((2.1, 3.5, 25.4, 20), (18, 6, 44, 22),
                    (-5, -4, 30, 20), (width-10, height-8, 30, 20),
                    (width+2, height+2, 10, 10), (-20, -20, 5, 5)))]
            boxes.append({"id": "not-text", "kind": "panel"})
            for selected in (boxes, [], [boxes[-1]]):
                self.assertEqual(typography.raster_contrast(foreground, background, mask, selected),
                    full_canvas_contrast(foreground, background, mask, selected))
            self.assertEqual(typography.raster_contrast(foreground, background, Image.new("L", size), boxes),
                full_canvas_contrast(foreground, background, Image.new("L", size), boxes))

    def test_luminance_does_not_process_unused_full_canvas(self):
        image = Image.new("RGB", (2000, 2600), "white")
        mask = Image.new("L", image.size, 255)
        boxes = [{"id": "small", "kind": "text", "bbox": {"x": 100, "y": 200, "width": 400, "height": 100}}]
        with patch.object(typography, "luminance", wraps=typography.luminance) as compute:
            typography.raster_contrast(image, image, mask, boxes)
        self.assertEqual([call.args[0].size for call in compute.call_args_list], [(400, 100), (400, 100)])


class ReviewInputTests(unittest.TestCase):
    def test_unknown_single_job_has_explicit_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(p.PipelineError, "Unknown job"):
                workflow.review_prepare({"jobs": []}, Path(temporary), "missing")

    def test_false_nonobject_annotations_do_not_turn_into_empty_annotations(self):
        with tempfile.TemporaryDirectory() as temporary:
            for invalid in ([], False, 0, ""):
                manifest = {"jobs": [{"id": "single", "status": "generated"}], "critical_details": []}
                before = copy.deepcopy(manifest)
                with self.assertRaisesRegex(p.PipelineError, "Annotations accept"):
                    workflow.review_prepare(manifest, Path(temporary), "single", {"single": invalid})
                self.assertEqual(manifest, before)


@unittest.skipUnless(os.environ.get("LC_LAYOUT_BROWSER_TEST") == "1", "opt-in pinned browser")
class ReviewBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lc-review-batch-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.m = create_v3_fixture(self.base)
        main = self.m["jobs"][0]
        jobs = [main]
        for index in (2, 3):
            job = copy.deepcopy(main)
            job.update(id=f"0{index}_local", kind="listing", text_mode="local_overlay",
                raw_output=f"raw/0{index}_local.png", final_output=f"final/0{index}_local.png",
                layout={"version": 3, "recipe": "photo_overlay", "text_groups": [
                    {"id": "title", "headline": "Fixture Detail", "box": [.06, .06, .88, .13]}]})
            jobs.append(job)
        self.m["jobs"] = jobs
        self.m["style_contract"] = {**typography.default_contract(),
            "color_roles": {"headline": "#25352A", "body": "#20262C", "accent": "#53684D"},
            "font_roles": {"headline": {"family": "sans", "weight": 600}}}
        for detail in self.m["critical_details"]:
            detail["visibility"] = {job["id"]: "required" for job in jobs}
        prepare_fixture(self.m, self.base)

    def test_ready_batch_uses_one_renderer_and_preserves_single_job_api_identity(self):
        before = {job["id"]: p.generation_fingerprint(self.m, job, self.base) for job in self.m["jobs"]}
        with patch.object(layout, "render_batch", wraps=layout.render_batch) as render:
            result = workflow.review_prepare_many(self.m, self.base)
        self.assertEqual(result["errors"], [])
        self.assertEqual(len(result["packets"]), 3)
        self.assertEqual(render.call_count, 1)
        self.assertEqual(len(render.call_args.args[2]), 2)
        job = self.m["jobs"][1]
        with patch.object(layout, "render_batch", side_effect=AssertionError("cache must not render")):
            self.assertTrue(workflow.review_prepare(self.m, self.base, job["id"])["cached"])
        self.assertIs(self.m["jobs"][1], job)
        self.assertEqual(before, {job["id"]: p.generation_fingerprint(self.m, job, self.base) for job in self.m["jobs"]})
        batch_records = [entry for job in self.m["jobs"] for entry in job.get("timings", [])
            if entry.get("stage") == "review_prepare" and len(entry.get("jobs", [])) == 3]
        self.assertEqual(len(batch_records), 1)

    def test_invalid_annotations_are_isolated_before_shared_preparation(self):
        before = copy.deepcopy(self.m["jobs"][1])
        with patch.object(layout, "render_batch", wraps=layout.render_batch) as render:
            result = workflow.review_prepare_many(self.m, self.base,
                annotations={"02_local": {"detail_output_bbox_norms": {"unknown": [.1, .1, .1, .1]}},
                             "03_local": {"detail_output_bbox_norms": {}}})
        self.assertEqual([entry["job"] for entry in result["errors"]], ["02_local"])
        self.assertEqual([entry["job"] for entry in result["packets"]], [MAIN_ID, "03_local"])
        self.assertEqual(self.m["jobs"][1], before)
        self.assertEqual(render.call_count, 1)
        self.assertEqual([j["id"] for j in render.call_args.args[2]], ["03_local"])

    def test_packet_failure_rolls_back_only_failed_job_after_shared_render(self):
        original = workflow._review_prepare_impl
        before = copy.deepcopy(self.m["jobs"][1])
        def fail_second(manifest, base, job_id, *args, **kwargs):
            result = original(manifest, base, job_id, *args, **kwargs)
            if job_id == "02_local":
                raise p.PipelineError("injected packet failure")
            return result
        with patch.object(workflow, "_review_prepare_impl", side_effect=fail_second), \
                patch.object(layout, "render_batch", wraps=layout.render_batch) as render:
            result = workflow.review_prepare_many(self.m, self.base)
        self.assertEqual([entry["job"] for entry in result["packets"]], [MAIN_ID, "03_local"])
        self.assertEqual([entry["job"] for entry in result["errors"]], ["02_local"])
        self.assertEqual(self.m["jobs"][1], before)
        self.assertFalse((self.base / "raw/02_local.png").exists())
        self.assertFalse((self.base / "review/layouts/02_local.png").exists())
        self.assertFalse((self.base / "review/packets/02_local.json").exists())
        self.assertTrue((self.base / "review/layouts/03_local.png").is_file())
        self.assertEqual(render.call_count, 1)
        self.assertEqual(p.read_json(self.base / "execution_plan.json"), p.execution_plan(self.m))

    def test_shared_prepare_exception_falls_back_without_starving_other_jobs(self):
        original = p.aspect_safe_postprocess
        def fail_second(manifest, base, *args, **kwargs):
            selected = kwargs.get("job_ids", [])
            if "02_local" in selected:
                original(manifest, base, *args, **kwargs)
                raise p.PipelineError("injected composition failure")
            return original(manifest, base, *args, **kwargs)
        before = copy.deepcopy(self.m["jobs"][1])
        with patch.object(p, "aspect_safe_postprocess", side_effect=fail_second):
            result = workflow.review_prepare_many(self.m, self.base)
        self.assertEqual([entry["job"] for entry in result["packets"]], [MAIN_ID, "03_local"])
        self.assertEqual([entry["job"] for entry in result["errors"]], ["02_local"])
        self.assertEqual(self.m["jobs"][1], before)
        self.assertFalse((self.base / "raw/02_local.png").exists())
        self.assertTrue((self.base / "review/layouts/03_local.png").is_file())

    def test_shared_commit_failure_discards_rolled_back_packet_errors_only(self):
        worker, writer = workflow._review_prepare_impl, p.write_json
        writes = 0
        before = copy.deepcopy(self.m["jobs"][:2])
        def fail_second(manifest, base, job_id, *args, **kwargs):
            result = worker(manifest, base, job_id, *args, **kwargs)
            if job_id == "02_local":
                raise p.PipelineError("injected packet failure")
            return result
        def fail_shared_commit(path, *args, **kwargs):
            nonlocal writes
            if Path(path).name == "execution_plan.json":
                writes += 1
                if writes == 2:
                    raise OSError("injected shared plan commit failure")
            return writer(path, *args, **kwargs)
        with patch.object(workflow, "_review_prepare_impl", side_effect=fail_second), \
                patch.object(p, "write_json", side_effect=fail_shared_commit):
            result = workflow.review_prepare_many(self.m, self.base,
                annotations={MAIN_ID: {"detail_output_bbox_norms": {"unknown": [.1, .1, .1, .1]}}})
        self.assertEqual([entry["job"] for entry in result["errors"]], [MAIN_ID, "02_local"])
        self.assertIn("Unknown detail", result["errors"][0]["error"])
        self.assertEqual([entry["job"] for entry in result["packets"]], ["03_local"])
        self.assertEqual(self.m["jobs"][:2], before)
        self.assertFalse((self.base / "raw/02_local.png").exists())
        self.assertFalse((self.base / "review/packets/02_local.json").exists())
        self.assertTrue((self.base / "review/layouts/03_local.png").is_file())
        self.assertGreaterEqual(writes, 4)

    def test_renderer_preview_reused_and_tampering_repaired_without_rerender(self):
        original = workflow._review_prepare_impl
        def ensure_no_second_thumbnail(*args, **kwargs):
            with patch.object(Image.Image, "thumbnail", side_effect=AssertionError("renderer already made preview")):
                return original(*args, **kwargs)
        with patch.object(workflow, "_review_prepare_impl", side_effect=ensure_no_second_thumbnail):
            # Exclude the text-free main passthrough, which needs its first preview.
            result = workflow.review_prepare_many(self.m, self.base, ["02_local", "03_local"])
        self.assertEqual(result["errors"], [])
        job = self.m["jobs"][1]
        preview = self.base / "review/layouts/02_local-360.png"
        expected = p.sha256_file(preview)
        raw_hash = p.sha256_file(self.base / job["raw_output"])
        Image.new("RGB", (360, 360), "blue").save(preview)
        with patch.object(layout, "render_batch", side_effect=AssertionError("preview repair must not render")):
            workflow.review_prepare(self.m, self.base, job["id"])
        self.assertEqual(p.sha256_file(preview), expected)
        self.assertEqual(p.sha256_file(self.base / job["raw_output"]), raw_hash)
        preview.unlink()
        workflow.review_prepare(self.m, self.base, job["id"])
        self.assertEqual(p.sha256_file(preview), expected)


if __name__ == "__main__":
    unittest.main()
