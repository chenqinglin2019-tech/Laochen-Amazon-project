"""Compact-delivery regressions with synthetic test-only review records."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, JpegImagePlugin

import lc_assets as assets
import lc_delivery as delivery
import lc_quality as quality
from pipeline_test_support import create_v3_fixture, bind_source_reviews


class CompactDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        for folder in ("raw", "final", "source", "review/layouts", "review/image_layers"):
            (self.base / folder).mkdir(parents=True, exist_ok=True)
        self.cache = self.base / "review/layouts/01.png"
        for relative in ("source/product.png", "raw/01.png", "final/01.jpg", "review/layouts/01.png", "review/layouts/01-360.png", "review/image_layers/01.png", "final/contact_sheet.png", "review/micro_detail_contact_sheet.png"):
            Image.new("RGB", (120, 100), "#f3e8cc").save(self.base / relative)
        self.job = {"id": "01", "status": "qa_passed", "raw_output": "raw/01.png", "final_output": "final/01.jpg", "recipe": "original", "canvas": [120, 100], "source_reference_ids": ["product"]}
        self.manifest = {"project_id": "test-fixture", "test_fixture": True,
                         "delivery_profile": "compact_jpg", "references": [{"id": "product", "path": "source/product.png"}], "jobs": [self.job]}
        self.report = {"jobs": [{"id": "01", "status": "qa_passed", "details": [], "fixture_observation": "Known synthetic fixture; not production evidence"}]}
        (self.base / "qa_report.json").write_text(json.dumps(self.report))
        self.job["qa_report_fingerprint"] = assets.digest(self.report["jobs"][0])
        self.job["qa_final_sha256"] = assets.file_hash(self.base / self.job["final_output"])
        self.job["qa_fingerprint"] = self.fingerprint(self.manifest, self.job, self.base)

    def tearDown(self):
        self.temp.cleanup()

    def fingerprint(self, manifest, job, base):
        return assets.digest({"recipe": job["recipe"], "input": assets.file_hash(base / "source/product.png"),
                              "final": assets.file_hash(base / job["final_output"]),
                              "artifact": delivery.artifact_sha256(manifest, job, base, self.cache)})

    def gate(self, manifest, base):
        return {"ready": all(job["status"] == "qa_passed" and self.fingerprint(manifest, job, base) == job["qa_fingerprint"] for job in manifest["jobs"])}

    def compact(self):
        return delivery.compact_project(self.manifest, self.base, manifest_path=self.base / "project_manifest.json", delivery_check_fn=self.gate, qa_fingerprint_fn=self.fingerprint)

    def test_compaction_persists_evidence_before_removing_only_owned_caches(self):
        (self.base / "review/layouts/user-notes.png").write_bytes(b"user-owned")
        result = self.compact()
        self.assertTrue(result["ready"])
        self.assertFalse(self.cache.exists())
        self.assertTrue((self.base / "review/layouts/user-notes.png").exists())
        for relative in ("source/product.png", "raw/01.png", "final/01.jpg", "qa_report.json"):
            self.assertTrue((self.base / relative).exists())
        disk = json.loads((self.base / "project_manifest.json").read_text())
        self.assertEqual(self.manifest["review_evidence"], disk["review_evidence"])
        record = json.loads((self.base / disk["review_evidence"]["01"]["path"]).read_text())
        self.assertEqual(self.report["jobs"][0], record["review_report"])
        self.assertTrue(self.gate(self.manifest, self.base)["ready"])
        self.assertEqual([], self.compact()["removed"])

    def test_missing_artifact_requires_real_evidence_and_changed_file_never_falls_back(self):
        original = self.cache.read_bytes()
        self.cache.unlink()
        self.assertIsNone(delivery.artifact_sha256(self.manifest, self.job, self.base, self.cache))
        self.cache.write_bytes(original)
        self.compact()
        self.cache.write_bytes(b"tampered")
        self.assertFalse(self.gate(self.manifest, self.base)["ready"])
        with self.assertRaisesRegex(ValueError, "Delivery gate"):
            self.compact()

    def test_changed_input_configuration_and_final_invalidate_compacted_approval(self):
        self.compact()
        self.job["recipe"] = "changed"
        self.assertFalse(self.gate(self.manifest, self.base)["ready"])
        self.job["recipe"] = "original"
        source = self.base / "source/product.png"
        original = source.read_bytes()
        source.write_bytes(b"changed real source")
        self.assertIsNone(delivery.artifact_sha256(self.manifest, self.job, self.base, self.cache))
        self.assertFalse(self.gate(self.manifest, self.base)["ready"])
        source.write_bytes(original)
        (self.base / self.job["final_output"]).write_bytes(b"changed final")
        self.assertFalse(self.gate(self.manifest, self.base)["ready"])

    def test_evidence_tampering_is_rejected(self):
        self.compact()
        path = self.base / self.manifest["review_evidence"]["01"]["path"]
        value = json.loads(path.read_text())
        value["review_report"]["fixture_observation"] = "modified"
        path.write_text(json.dumps(value))
        self.assertIsNone(delivery.artifact_sha256(self.manifest, self.job, self.base, self.cache))

    def test_unfinished_project_and_legacy_project_cannot_be_cleaned(self):
        self.manifest["jobs"].append({"id": "02", "status": "pending", "required": False})
        with self.assertRaises(ValueError):
            delivery.persist_review_evidence(self.manifest, self.base, self.report, self.fingerprint)
        self.manifest["jobs"].pop()
        self.manifest.pop("delivery_profile")
        with self.assertRaisesRegex(ValueError, "explicitly adopt"):
            self.compact()
        self.assertTrue(self.cache.exists())

    def test_reused_asset_in_cache_directory_is_retained(self):
        self.job["product_layers"] = [{"asset_path": "review/layouts/01.png"}]
        self.compact()
        self.assertTrue(self.cache.exists())

    def test_image_inset_in_cache_is_a_retained_input(self):
        self.job["layout"] = {"items": [{"image": "review/layouts/01.png", "evidence_refs": ["product"]}]}
        self.compact()
        self.assertTrue(self.cache.exists())
        self.assertIn(self.cache.resolve(), delivery.retained_input_paths(self.manifest, self.base))

    def test_registered_retired_attempts_are_cleaned_but_other_raw_files_are_retained(self):
        for name in ("old", "unregistered"):
            Image.new("RGB", (64, 64), "white").save(self.base / f"raw/{name}.png")
        self.job["generation_attempts"] = [{"id": "first", "status": "ingested", "retained_artifact_path": "raw/old.png", "artifact_sha256": assets.file_hash(self.base / "raw/old.png")}, {"id": "adopted", "status": "ingested", "retained_artifact_path": "raw/01.png", "artifact_sha256": assets.file_hash(self.base / "raw/01.png")}]
        self.compact()
        self.assertFalse((self.base / "raw/old.png").exists())
        self.assertTrue((self.base / "raw/unregistered.png").exists())
        self.assertTrue((self.base / "raw/01.png").exists())
        self.assertEqual(2, len(self.job["generation_attempts"]))

    def test_repair_target_and_actual_attachment_remain_current_inputs(self):
        target = self.base / "raw/old.png"
        target.write_bytes(b"actual earlier tool output")
        attachment = self.base / "review/layouts/01-360.png"
        self.job.update(prompt_edit={"target_path": "raw/old.png", "failures": ["fixture failure"]},
                        generation_reference_paths=[str(attachment)])
        self.job["generation_attempts"] = [{"id": "old", "status": "ingested", "retained_artifact_path": "raw/old.png", "artifact_sha256": assets.file_hash(target)}]
        result = self.compact()
        self.assertTrue(result["ready"])
        self.assertTrue(target.is_file())
        self.assertTrue(attachment.is_file())
        record = json.loads((self.base / self.manifest["review_evidence"]["01"]["path"]).read_text())
        self.assertIn("raw/old.png", record["input_files"])
        self.assertIn("review/layouts/01-360.png", record["input_files"])

    def test_actual_attachment_provenance_recursively_retains_real_sources(self):
        for name in ("adopted", "restored", "original"):
            (self.base / f"source/{name}.png").write_bytes(name.encode())
        self.manifest["references"] += [
            {"id": "adopted", "path": "source/adopted.png", "provenance": {"source_reference_ids": ["restored"]}},
            {"id": "restored", "path": "source/restored.png", "provenance": {"source_reference_ids": ["original"]}},
            {"id": "original", "path": "source/original.png"},
        ]
        self.job["generation_reference_paths"] = ["source/adopted.png"]
        self.compact()
        record = json.loads((self.base / self.manifest["review_evidence"]["01"]["path"]).read_text())
        self.assertTrue({"source/adopted.png", "source/restored.png", "source/original.png"} <= record["input_files"].keys())

    def test_failed_post_gate_restores_exact_manifest_caches_and_bindings(self):
        path = self.base / "project_manifest.json"
        original = json.dumps(self.manifest, separators=(",", ":")).encode()
        path.write_bytes(original)
        before = copy.deepcopy(self.manifest)
        images = {str(item.relative_to(self.base)): item.read_bytes() for item in self.base.rglob("*.png")}
        with patch.object(self, "gate", wraps=self.gate) as original_gate:
            # Keep the actual pre-gate while failing only the post-cleanup gate.
            with self.assertRaisesRegex(ValueError, "rolled back"):
                delivery.compact_project(self.manifest, self.base, manifest_path=path,
                    delivery_check_fn=lambda m, b: original_gate(m, b) if self.cache.exists() else {"ready": False},
                    qa_fingerprint_fn=self.fingerprint)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.manifest, before)
        for relative, payload in images.items():
            self.assertEqual((self.base / relative).read_bytes(), payload)
        self.assertTrue(self.gate(self.manifest, self.base)["ready"])

    def test_process_exit_after_staging_is_rolled_back_on_next_manifest_lock(self):
        path = self.base / "project_manifest.json"
        original = json.dumps(self.manifest).encode()
        path.write_bytes(original)
        code = '''
import json, os, sys
from pathlib import Path
import lc_assets as assets
import lc_delivery as delivery
base = Path(sys.argv[1])
path = base / "project_manifest.json"
manifest = json.loads(path.read_text())
def fingerprint(m, j, b):
    return assets.digest({"recipe": j["recipe"], "input": assets.file_hash(b / "source/product.png"),
        "final": assets.file_hash(b / j["final_output"]),
        "artifact": delivery.artifact_sha256(m, j, b, b / "review/layouts/01.png")})
def gate(m, b):
    if not (b / "review/layouts/01.png").exists():
        os._exit(17)
    return {"ready": True}
delivery.compact_project(manifest, base, manifest_path=path, delivery_check_fn=gate, qa_fingerprint_fn=fingerprint)
'''
        result = subprocess.run([sys.executable, "-c", code, str(self.base)], cwd=Path(__file__).parent, capture_output=True, text=True)
        self.assertEqual(result.returncode, 17, result.stderr)
        self.assertFalse(self.cache.exists())
        from lc_workflow import manifest_lock
        with manifest_lock(path):
            self.assertTrue(self.cache.exists())
            self.assertEqual(path.read_bytes(), original)
        self.assertTrue(self.gate(self.manifest, self.base)["ready"])

    def test_interrupted_purge_finishes_without_rolling_back_passed_cleanup(self):
        with patch("lc_delivery._purge_compaction_files", side_effect=OSError("fixture purge interruption")):
            with self.assertRaisesRegex(OSError, "purge interruption"):
                self.compact()
        self.assertFalse(self.cache.exists())
        result = delivery.recover_compaction(self.manifest, self.base, manifest_path=self.base / "project_manifest.json")
        self.assertEqual(result[0]["state"], "finished")
        self.assertTrue(self.gate(self.manifest, self.base)["ready"])
        self.assertEqual([], self.compact()["removed"])

    def test_quarantine_recovery_rejects_traversal_without_touching_user_files(self):
        with patch("lc_delivery._purge_compaction_files", side_effect=OSError("fixture stop before purge")):
            with self.assertRaises(OSError):
                self.compact()
        journal_path = next((self.base / ".lc-compaction").glob("tx-*/journal.json"))
        journal = json.loads(journal_path.read_text())
        source = self.base / "source/product.png"
        original = source.read_bytes()
        journal["files"].append({"relative": "../../../source/product.png", "sha256": assets.file_hash(source)})
        journal_path.write_text(json.dumps(journal))
        with self.assertRaisesRegex(ValueError, "invalid journal artifact"):
            delivery.recover_compaction(self.manifest, self.base, manifest_path=self.base / "project_manifest.json")
        self.assertEqual(source.read_bytes(), original)

    def test_exact_input_restoration_reuses_existing_approval_without_rebinding(self):
        self.compact()
        before = copy.deepcopy(self.manifest)
        source = self.base / "source/product.png"
        payload = source.read_bytes()
        source.unlink()
        self.assertIsNone(delivery.artifact_sha256(self.manifest, self.job, self.base, self.cache))
        source.write_bytes(payload)
        self.assertTrue(self.gate(self.manifest, self.base)["ready"])
        self.assertEqual(self.manifest, before)

    def test_unrelated_image_change_does_not_remove_this_jobs_missing_cache_binding(self):
        Image.new("RGB", (120, 100), "white").save(self.base / "source/unrelated.png")
        self.manifest["references"].append({"id": "unrelated", "path": "source/unrelated.png"})
        self.compact()
        (self.base / "source/unrelated.png").write_bytes(b"changed unrelated source")
        self.assertIsNotNone(delivery.artifact_sha256(self.manifest, self.job, self.base, self.cache))

    def test_source_metrics_reuse_after_cleanup_and_on_demand_rebuild(self):
        from unittest.mock import patch
        self.manifest["references"][0]["product_bbox_norm"] = [0, 0, 1, 1]
        quality.assess_sources(self.manifest, self.base)
        metrics = copy.deepcopy(self.manifest["references"][0]["quality_metrics"])
        self.compact()
        root = self.base / "review/source_quality"
        self.assertFalse(list(root.glob("*.png")))
        with patch("lc_quality.Image.open", side_effect=AssertionError("unchanged reviewed source should reuse metrics")):
            quality.assess_sources(self.manifest, self.base, materialize=False)
        self.assertEqual(metrics, self.manifest["references"][0]["quality_metrics"])
        original_final = (self.base / "final/01.jpg").read_bytes()
        (self.base / "final/01.jpg").write_bytes(b"changed final, same real source")
        self.assertTrue(delivery.source_cache_metadata_is_current(self.manifest, self.base))
        (self.base / "final/01.jpg").write_bytes(original_final)
        quality.assess_sources(self.manifest, self.base, materialize=True)
        self.assertTrue(list(root.glob("*.png")))

    def test_traversal_and_symlink_candidates_are_rejected(self):
        for value in ("../escape.png", "source/product.png", "review/../source/product.png"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                delivery._cache_path(self.base, value)
        target = self.base / "review/layouts/01-360.png"
        target.unlink()
        target.symlink_to(self.base / "source/product.png")
        with self.assertRaisesRegex(ValueError, "Symlink"):
            self.compact()
        self.assertTrue(self.cache.exists())
        self.assertTrue((self.base / "source/product.png").is_file())
        (self.base / "review/root-link").symlink_to(self.base, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "Symlink"):
            delivery._cache_path(self.base.resolve(), self.base / "review/root-link/review/layouts/01.png")

    def test_jpg_profile_legacy_compatibility_quality_and_dimensions(self):
        job = {"final_output": "final/example.png", "export": {}}
        delivery.apply_delivery_profile({}, job)
        self.assertTrue(job["final_output"].endswith(".png"))
        delivery.apply_delivery_profile(self.manifest, job)
        self.assertEqual("final/example.jpg", job["final_output"])
        self.assertEqual(92, job["export"]["quality"])
        job["export"]["quality"] = 95
        delivery.apply_delivery_profile(self.manifest, job)
        self.assertEqual(95, job["export"]["quality"])
        job.update(canvas=[120, 100], image_sha256="synthetic-fixture", ai_disclosure={"human_source": "none", "reviewed_image_sha256": "synthetic-fixture"})
        exported = assets.export_image(Image.new("RGB", (120, 100), "white"), job, self.base / job["final_output"])
        self.assertEqual(95, exported["encoding"]["quality"])
        with Image.open(self.base / job["final_output"]) as image:
            self.assertEqual(0, JpegImagePlugin.get_sampling(image))
            self.assertEqual((120, 100), image.size)
        job["export"]["quality"] = 80
        with self.assertRaises(ValueError):
            delivery.apply_delivery_profile(self.manifest, job)

    def test_standalone_html_is_removed_and_false_legacy_flag_is_compatible(self):
        self.manifest["delivery_profile"] = {"name": "compact_jpg", "standalone_html": False,
                                            "preview_long_edge": 1600, "preview_quality": 88}
        self.assertEqual(delivery.resolve_delivery_profile(self.manifest), {"name": "compact_jpg", "jpeg_quality": 92})
        self.manifest["delivery_profile"]["standalone_html"] = True
        with self.assertRaisesRegex(ValueError, "no longer supported"):
            delivery.resolve_delivery_profile(self.manifest)
        self.assertFalse(hasattr(delivery, "build_standalone_html"))


class MetadataOnlyQualityTests(unittest.TestCase):
    def test_metadata_only_computes_real_metrics_without_writing_image_caches(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            manifest = create_v3_fixture(base)
            quality.assess_sources(manifest, base, materialize=False)
            self.assertFalse(list((base / "review/source_quality").glob("*.png")))
            previous_hash = manifest["references"][0]["sha256"]
            previous_metrics = copy.deepcopy(manifest["references"][0]["quality_metrics"])
            quality.assess_sources(manifest, base, materialize=True)
            self.assertTrue(list((base / "review/source_quality").glob("*.png")))
            self.assertEqual(previous_metrics, manifest["references"][0]["quality_metrics"])
            bind_source_reviews(manifest, base)
            Image.new("RGB", (1600, 1600), "black").save(base / "source/product_front.png")
            quality.assess_sources(manifest, base, materialize=False)
            self.assertNotEqual(previous_hash, manifest["references"][0]["sha256"])
            self.assertIn("SOURCE_REVIEW_STALE:product_front", quality._review_problems(manifest["references"][0]))


if __name__ == "__main__":
    unittest.main()
