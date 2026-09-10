"""Synthetic regression for batch annotation/render/submission geometry binding."""
from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

import lc_image_pipeline as pipeline
import lc_workflow as workflow
from pipeline_test_support import (MAIN_ID, SECONDARY_ID, SOURCE_BOX, NOTE,
                                   create_v3_fixture, prepare_fixture,
                                   simulate_secondary_output)


class ReviewGeometryTests(unittest.TestCase):
    def _run_batch(self, base: Path, *, annotate_composite: bool) -> dict:
        manifest = create_v3_fixture(base)
        manifest.update(delivery_profile={"name": "compact_jpg", "jpeg_quality": 92},
                        review_dependency_version=2, generation_dependency_version=2)
        prepare_fixture(manifest, base)
        simulate_secondary_output(manifest, base)
        secondary = pipeline.find_by_id(manifest["jobs"], SECONDARY_ID)
        annotations = {SECONDARY_ID: {
            "raw_product_bbox_norm": copy.deepcopy(secondary["target_product_bbox_norm"]),
            "detail_output_bbox_norms": copy.deepcopy(secondary["fixture_output_detail_boxes"]),
        }}
        if annotate_composite:
            # This legitimate rounded observation differs from the compositor's
            # r-x arithmetic (0.6000000000000001), although its pixels do not.
            annotations[MAIN_ID] = {"raw_product_bbox_norm": SOURCE_BOX.copy()}
        attempts = {job["id"]: copy.deepcopy(job.get("generation_attempts", []))
                    for job in manifest["jobs"]}
        dispatches = {job["id"]: job.get("metrics", {}).get("model_dispatches", 0)
                      for job in manifest["jobs"]}

        # All model stand-ins are already present. Review preparation/submission
        # must not start or ingest another attempt, including for the local main.
        with patch.object(pipeline, "transition_job", side_effect=AssertionError("No model dispatch during review")), \
                patch.object(workflow, "ingest", side_effect=AssertionError("No model ingest during review")):
            prepared = workflow.review_prepare_many(manifest, base, annotations=annotations)
            self.assertEqual(prepared["errors"], [])
            self.assertEqual([item["job"] for item in prepared["packets"]], [MAIN_ID, SECONDARY_ID])
            self.assertTrue(manifest.get("test_fixture"), "Never infer production verdicts")
            packets = []
            for item in prepared["packets"]:
                packet = pipeline.read_json(Path(item["packet"]))
                self.assertEqual(packet["missing_annotations"], [])
                for field in ("semantic_qa_results", "policy_qa_results", "detail_qa_results"):
                    for key in packet["reviews"][field]:
                        packet["reviews"][field][key] = {"verdict": "pass", "notes": NOTE}
                packet["reviews"]["ai_disclosure"] = {"human_source": "none", "notes": NOTE}
                packets.append(packet)
            prepared_geometry = {job["id"]: workflow.annotation_fingerprint(job) for job in manifest["jobs"]}
            prepared_pixels = {job["id"]: self._pixel_hash(base / "review/layouts" / f"{job['id']}.png")
                               for job in manifest["jobs"]}
            submitted = workflow.review_submit_many(manifest, base, packets)

        self.assertEqual(submitted["errors"], [])
        self.assertEqual([(item["job"], item["status"]) for item in submitted["results"]],
                         [(MAIN_ID, "qa_passed"), (SECONDARY_ID, "qa_passed")])
        self.assertEqual(prepared_geometry, {job["id"]: workflow.annotation_fingerprint(job)
                                             for job in manifest["jobs"]})
        self.assertEqual(prepared_pixels, {job["id"]: self._pixel_hash(base / "review/layouts" / f"{job['id']}.png")
                                           for job in manifest["jobs"]})
        self.assertEqual(attempts, {job["id"]: job.get("generation_attempts", []) for job in manifest["jobs"]})
        self.assertEqual(dispatches, {job["id"]: job.get("metrics", {}).get("model_dispatches", 0)
                                     for job in manifest["jobs"]})
        return {job["id"]: {"raw": pipeline.sha256_file(base / job["raw_output"]),
                            "layout_pixels": prepared_pixels[job["id"]],
                            "final": pipeline.sha256_file(base / job["final_output"])}
                for job in manifest["jobs"]}

    @staticmethod
    def _pixel_hash(path: Path) -> str:
        import hashlib
        with Image.open(path) as image:
            return hashlib.sha256(image.convert("RGB").tobytes()).hexdigest()

    def test_rounded_batch_annotation_passes_first_submit_without_pixel_or_model_changes(self):
        with tempfile.TemporaryDirectory(prefix="lc-review-geometry-") as temporary:
            base = Path(temporary).resolve()
            rounded = self._run_batch(base / "rounded", annotate_composite=True)
            control = self._run_batch(base / "control", annotate_composite=False)
            self.assertEqual(rounded, control)


if __name__ == "__main__":
    unittest.main()
