"""Manifest/CLI boundary regressions; no model calls or real product data."""
from __future__ import annotations
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from PIL import Image
import lc_image_pipeline as pipeline

ROOT = Path(__file__).resolve().parents[1]


class ManifestValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lc-v3-validation-")
        self.base = Path(self.temp.name).resolve()
        (self.base / "source").mkdir()
        Image.new("RGB", (64, 64), "white").save(self.base / "source/product_front.png")
        self.manifest = json.loads((ROOT / "assets/project_manifest.template.json").read_text())
        self.manifest.update(project_id="validation", marketplace="US", language="en")

    def tearDown(self):
        self.temp.cleanup()

    def changed(self, keys, value):
        manifest = copy.deepcopy(self.manifest)
        parent = manifest
        for key in keys[:-1]:
            parent = parent[key]
        parent[keys[-1]] = value
        return manifest

    def reject(self, manifest):
        errors = pipeline.validate_manifest(manifest, self.base, check_files=False)
        self.assertTrue(errors, "Malformed input was accepted")
        self.assertTrue(all(isinstance(error, str) for error in errors))
        return errors

    def test_unknown_reviews_pass_schema_then_quality_gate_blocks(self):
        self.assertEqual([], pipeline.validate_manifest(self.manifest, self.base))
        pipeline.prepare(self.manifest, self.base)
        self.assertTrue(all(job["status"] == "blocked" for job in self.manifest["jobs"]))
        self.assertTrue(all(job.get("attempts", 0) == 0 for job in self.manifest["jobs"]))

    def test_nonobject_roots_and_nested_collections_report_errors(self):
        for root in (None, [], "manifest", 1, True):
            with self.subTest(root=root):
                self.reject(root)
        for path in (("product_truth",), ("references",), ("references", 0), ("jobs",),
                     ("jobs", 0), ("critical_details",), ("facts",), ("shared_blockers",),
                     ("jobs", 1, "layout"), ("jobs", 1, "layout", "items"),
                     ("jobs", 1, "layout", "protected_regions"),
                     ("jobs", 1, "source_reference_ids"), ("jobs", 1, "product_layers")):
            with self.subTest(path=path):
                self.reject(self.changed(path, None))

    def test_nonhashable_identifiers_and_enums_do_not_crash(self):
        paths = (("run_mode",), ("generation_backend",), ("references", 0, "id"),
                 ("references", 0, "visual_quality"), ("jobs", 1, "id"),
                 ("jobs", 1, "kind"), ("jobs", 1, "render_mode"),
                 ("jobs", 1, "layout", "template"), ("jobs", 1, "ai_disclosure", "human_source"))
        for path in paths:
            for value in ([], {"value": "bad"}):
                with self.subTest(path=path, value=value):
                    self.reject(self.changed(path, value))

    def test_v3_shapes_are_validated_by_validate_command(self):
        cases = [
            (("references", 0, "quality_review"), None),
            (("references", 0, "quality_review"), {"clarity": ["clear"]}),
            (("references", 0, "provenance"), {"source_reference_ids": [None]}),
            (("jobs", 1, "source_assessment"), "matched"),
            (("jobs", 1, "ai_disclosure"), []),
            (("jobs", 1, "ai_disclosure", "reviewed_visual_fingerprint"), []),
            (("jobs", 1, "disclosure_visual_fingerprint"), None),
            (("jobs", 1, "disclosure_extra_images"), [None]),
            (("jobs", 1, "export"), None),
            (("jobs", 1, "export"), {"keywords": "one-keyword"}),
            (("jobs", 1, "claim_ids"), None),
            (("jobs", 1, "layout", "items"), [None]),
            (("jobs", 1, "layout", "font_sizes"), {"headline": float("nan")}),
            (("jobs", 1, "layout", "items"), [{"text": "Point", "target": [True, 0.5]}]),
            (("jobs", 1, "product_layers"), [{"reference_id": "product_front", "shadow": None}]),
            (("jobs", 1, "product_layers"), [{"reference_id": "product_front", "shadow": {"offset": [1]}}]),
            (("language",), ["en"]),
        ]
        for path, value in cases:
            with self.subTest(path=path, value=value):
                self.reject(self.changed(path, value))

    def test_canvas_bounds_include_aplus_and_exclude_bool(self):
        for kind in ("listing", "a_plus"):
            for dimensions in ([10001, 10001], [10**400, 10**400], [True, True],
                               [2000.0, 2000], [0, 2000], [float("inf"), 2000]):
                with self.subTest(kind=kind, dimensions=dimensions):
                    manifest = copy.deepcopy(self.manifest)
                    manifest["jobs"][1].update(kind=kind, a_plus_module="requested-module", canvas=dimensions)
                    self.reject(manifest)
        for dimensions in ([1600, 1600], [2000, 2600]):
            manifest = self.changed(("jobs", 1, "canvas"), dimensions)
            self.assertEqual([], pipeline.validate_manifest(manifest, self.base))

    def test_integer_and_normalized_geometry_boundary_values(self):
        for value in (True, float("nan"), float("inf"), 10**400):
            self.reject(self.changed(("concurrency",), value))
            self.reject(self.changed(("jobs", 1, "target_product_bbox_norm"), [0, 0, value, 1]))
        for box in ([0, 0, 0, 1], [-0.1, 0, 1, 1], [0.9, 0, 0.2, 1], [0, 0, 1]):
            self.reject(self.changed(("references", 0, "product_bbox_norm"), box))

    def test_empty_or_malformed_file_paths_and_directory_outputs(self):
        for path in (("references", 0, "path"), ("jobs", 1, "raw_output"), ("jobs", 1, "final_output")):
            for value in (None, "", "  ", [], {"path": "x.png"}, "bad\x00.png", "https://example.com/image.png"):
                with self.subTest(path=path, value=value):
                    self.reject(self.changed(path, value))
        (self.base / "folder.png").mkdir()
        self.reject(self.changed(("jobs", 1, "final_output"), "folder.png"))
        self.reject(self.changed(("jobs", 1, "raw_output"), "project_manifest.json"))

    def test_output_traversal_symlink_and_input_overwrite_are_rejected(self):
        for value in ("../outside.png", str(self.base / "absolute.png")):
            self.reject(self.changed(("jobs", 1, "final_output"), value))
        outside = Path(self.temp.name).parent / "outside.png"
        (self.base / "escape.png").symlink_to(outside)
        self.reject(self.changed(("jobs", 1, "final_output"), "escape.png"))
        self.reject(self.changed(("jobs", 1, "raw_output"), "source/product_front.png"))
        self.reject(self.changed(("jobs", 1, "final_output"), self.manifest["jobs"][0]["final_output"]))

    def test_missing_source_file_can_only_skip_existence_check(self):
        manifest = self.changed(("references", 0, "path"), "source/missing.png")
        self.assertTrue(pipeline.validate_manifest(manifest, self.base))
        self.assertEqual([], pipeline.validate_manifest(manifest, self.base, check_files=False))
        self.reject(self.changed(("references", 0, "path"), []))

    def test_detail_locations_visibility_and_verdicts_are_typed(self):
        detail = {"id": "port", "name": "Port", "priority": "P0", "status": "unknown",
                  "evidence_level": "unknown", "visual_confirmation": "unknown", "locations": [],
                  "visibility": {job["id"]: "hidden" for job in self.manifest["jobs"]}}
        self.manifest["critical_details"] = [detail]
        self.assertEqual([], pipeline.validate_manifest(self.manifest, self.base))
        for path, value in ((("critical_details", 0, "locations"), [None]),
                            (("critical_details", 0, "visibility"), None),
                            (("critical_details", 0, "priority"), []),
                            (("jobs", 1, "semantic_qa_results"), {"clarity": []}),
                            (("jobs", 1, "detail_qa_results"), {"port": {"verdict": ["pass"]}})):
            self.reject(self.changed(path, value))

    def test_cli_validation_returns_diagnostic_without_traceback(self):
        fixtures = [None, self.changed(("jobs", 1, "layout"), None),
                    self.changed(("run_mode",), []), self.changed(("jobs", 1, "canvas"), [100000, 100000]),
                    self.changed(("jobs", 1, "export"), None)]
        for index, manifest in enumerate(fixtures):
            with self.subTest(index=index):
                path = self.base / f"invalid-{index}.json"
                path.write_text(json.dumps(manifest))
                result = subprocess.run([sys.executable, str(ROOT / "scripts/lc_image_pipeline.py"), "validate",
                                         "--manifest", str(path), "--skip-file-check"], capture_output=True, text=True, timeout=10)
                self.assertEqual(2, result.returncode, result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertIn("Manifest validation failed", result.stderr)


if __name__ == "__main__":
    unittest.main()
