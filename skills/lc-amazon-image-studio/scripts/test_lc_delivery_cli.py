"""Real CLI entrypoint/gate regressions using marked synthetic image fixtures."""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import lc_image_pipeline as pipeline
from lc_assets import file_hash
from pipeline_test_support import create_v3_fixture, prepare_fixture, simulate_secondary_output, finish_fixture


class DeliveryCLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lc-delivery-cli-")
        self.base = Path(self.temp.name).resolve()
        self.path = self.base / "project_manifest.json"

    def tearDown(self):
        self.temp.cleanup()

    def cli(self, *arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(sys, "argv", ["lc_image_pipeline.py", *arguments, "--json"]), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = pipeline.main()
        return code, json.loads(stdout.getvalue()), stderr.getvalue()

    def ready(self, *, compact, scattered=False):
        manifest = create_v3_fixture(self.base)
        if compact:
            manifest["delivery_profile"] = {"name": "compact_jpg", "jpeg_quality": 92}
        if scattered:
            for job in manifest["jobs"]:
                job["final_output"] = f"legacy/{job['id']}/image.png"
        prepare_fixture(manifest, self.base)
        # Deterministic fixture drawing through real transition/ingest bindings;
        # this helper never invokes any image-generation service.
        simulate_secondary_output(manifest, self.base)
        finish_fixture(manifest, self.base)
        return manifest

    def assert_inventory(self, result, manifest):
        output = Path(result["output_dir"])
        self.assertTrue(output.is_dir())
        self.assertEqual(result["image_count"], len(manifest["jobs"]))
        self.assertEqual({entry["job_id"] for entry in result["images"]}, {job["id"] for job in manifest["jobs"]})
        expected = {job["id"]: job["qa_final_sha256"] for job in manifest["jobs"]}
        self.assertEqual({path.name for path in output.iterdir()}, {entry["filename"] for entry in result["images"]})
        for entry in result["images"]:
            self.assertEqual(Path(entry["path"]).parent, output)
            self.assertEqual(file_hash(Path(entry["path"])), expected[entry["job_id"]])
            self.assertEqual(entry["sha256"], expected[entry["job_id"]])
        report = json.loads((self.base / "delivery_report.json").read_text())
        for key in ("output_dir", "images", "image_count"):
            self.assertEqual(report[key], result[key])
        self.assertFalse(list(self.base.rglob("*.zip")))

    def test_init_declares_flat_jpg_paths_for_listing_and_a_plus(self):
        code, result, stderr = self.cli("init", "--project-dir", str(self.base), "--project-id", "delivery-init-fixture",
                                       "--marketplace", "US", "--language", "en", "--include-a-plus",
                                       "--a-plus-module", "standard-header", "--a-plus-canvas", "1464", "600")
        self.assertEqual(code, 0, stderr or result)
        manifest = json.loads(self.path.read_text())
        self.assertEqual(len(manifest["jobs"]), 13)
        for job in manifest["jobs"]:
            path = Path(job["final_output"])
            self.assertEqual(path.parent, Path("final"))
            self.assertEqual(path.suffix, ".jpg")

    def test_compact_cli_runs_two_real_gates_and_reuses_clean_final(self):
        manifest = self.ready(compact=True)
        before = {job["id"]: ((self.base / job["final_output"]).stat().st_mtime_ns, file_hash(self.base / job["final_output"])) for job in manifest["jobs"]}
        actual_gate = pipeline.delivery_check
        with patch.object(pipeline, "delivery_check", wraps=actual_gate) as gate, \
             patch.object(pipeline, "export_image", side_effect=AssertionError("Delivery must not encode final images")), \
             patch("lc_delivery.shutil.copy2", side_effect=AssertionError("Clean final must not be copied")):
            code, result, stderr = self.cli("deliver", "--manifest", str(self.path))
        self.assertEqual(code, 0, stderr or result)
        self.assertEqual(gate.call_count, 2)
        self.assertEqual(result["output_dir"], str(self.base / "final"))
        self.assertEqual(result["copied_files"], 0)
        self.assertNotIn("delivery_result", result["compaction"])
        self.assert_inventory(result, manifest)
        with patch.object(pipeline, "delivery_check", wraps=actual_gate) as repeated_gate, \
             patch.object(Image.Image, "save", side_effect=AssertionError("Unchanged deliver must not encode images")), \
             patch("lc_delivery.shutil.copy2", side_effect=AssertionError("Unchanged deliver must not copy")):
            code, second, stderr = self.cli("deliver", "--manifest", str(self.path))
        self.assertEqual(code, 0, stderr or second)
        self.assertEqual(repeated_gate.call_count, 2)
        self.assertEqual(second["compaction"]["removed"], [])
        self.assertEqual(second["images"], result["images"])
        self.assertEqual(before, {job["id"]: ((self.base / job["final_output"]).stat().st_mtime_ns, file_hash(self.base / job["final_output"])) for job in manifest["jobs"]})

    def test_legacy_cli_collects_original_png_format_without_cleanup(self):
        manifest = self.ready(compact=False, scattered=True)
        before = {job["id"]: (self.base / job["final_output"]).read_bytes() for job in manifest["jobs"]}
        actual_gate = pipeline.delivery_check
        with patch.object(pipeline, "delivery_check", wraps=actual_gate) as gate, \
             patch("lc_delivery.compact_project", side_effect=AssertionError("Legacy projects must not be compacted")):
            code, result, stderr = self.cli("deliver", "--manifest", str(self.path))
        self.assertEqual(code, 0, stderr or result)
        self.assertEqual(gate.call_count, 1)
        self.assertTrue(all(entry["filename"].endswith(".png") for entry in result["images"]))
        self.assertNotIn("compaction", result)
        self.assertEqual(result["copied_files"], len(manifest["jobs"]))
        self.assertTrue((self.base / "final/contact_sheet.png").is_file())
        self.assert_inventory(result, manifest)
        with patch("lc_delivery.shutil.copy2", side_effect=AssertionError("Legacy repeat must reuse approved copies")), \
             patch.object(Image.Image, "save", side_effect=AssertionError("Legacy repeat must not encode")):
            code, second, stderr = self.cli("deliver", "--manifest", str(self.path))
        self.assertEqual(code, 0, stderr or second)
        self.assertEqual(second["output_dir"], result["output_dir"])
        self.assertEqual(second["copied_files"], 0)
        self.assertEqual(before, {job["id"]: (self.base / job["final_output"]).read_bytes() for job in manifest["jobs"]})

    def test_failed_current_gate_does_not_publish_or_clean(self):
        manifest = self.ready(compact=True)
        (self.base / manifest["jobs"][0]["final_output"]).write_bytes(b"tampered after synthetic QA")
        code, result, stderr = self.cli("deliver", "--manifest", str(self.path))
        self.assertEqual(code, 2)
        self.assertFalse(result["ok"])
        self.assertNotIn("output_dir", result)
        self.assertFalse((self.base / "delivery").exists())
        self.assertTrue((self.base / "final/contact_sheet.png").is_file())

    def test_invalid_asset_lists_fail_through_structured_cli_validation(self):
        for field in ("product_layers", "disclosure_extra_images", "items"):
            base = self.base / field
            manifest = create_v3_fixture(base)
            job = manifest["jobs"][1]
            (job["layout"] if field == "items" else job)[field] = 7
            path = base / "project_manifest.json"
            pipeline.write_json(path, manifest)
            before = path.read_bytes()
            code, result, stderr = self.cli("prepare", "--manifest", str(path), "--jobs", job["id"])
            self.assertEqual(code, 2, (field, result, stderr))
            self.assertFalse(result["ok"])
            self.assertIn("must be an array", result["error"])
            self.assertEqual(before, path.read_bytes())


if __name__ == "__main__":
    unittest.main()
