"""No-model regression tests for scoped snapshots and flat image delivery."""
from __future__ import annotations

import copy
import json
import multiprocessing
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import lc_delivery as delivery
import lc_transactions as transactions
from lc_assets import file_hash


def _delivery_worker(base, manifest, release, outcomes):
    try:
        if not release.wait(15):
            raise RuntimeError("Worker release timed out")
        outcomes.put(delivery.prepare_delivery_directory(manifest, Path(base), delivery_result={"ready": True}))
    except Exception as exc:
        outcomes.put({"error": str(exc)})


class DeliveryDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lc-delivery-directory-")
        self.base = Path(self.temp.name).resolve()
        (self.base / "final").mkdir()
        self.manifest = {"project_id": "directory-fixture", "jobs": []}
        for identifier in ("a", "b"):
            path = self.base / "final" / f"{identifier}.jpg"
            path.write_bytes(("approved synthetic fixture " + identifier).encode())
            self.manifest["jobs"].append({"id": identifier, "status": "qa_passed", "required": True,
                                           "final_output": str(path.relative_to(self.base)), "qa_final_sha256": file_hash(path)})

    def tearDown(self):
        self.temp.cleanup()

    def deliver(self):
        return delivery.prepare_delivery_directory(self.manifest, self.base, delivery_result={"ready": True, "project_id": self.manifest["project_id"]})

    def test_clean_final_is_returned_without_copying_or_writing(self):
        before = {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in (self.base / "final").iterdir()}
        with patch("lc_delivery.shutil.copy2", side_effect=AssertionError("Clean final must not copy")):
            first, second = self.deliver(), self.deliver()
        self.assertEqual(first["output_dir"], str(self.base / "final"))
        self.assertEqual(first, second)
        self.assertEqual(first["image_count"], 2)
        self.assertEqual(first["copied_files"], 0)
        self.assertFalse((self.base / "delivery").exists())
        self.assertEqual(before, {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in (self.base / "final").iterdir()})

    def test_extra_final_content_creates_image_only_version_and_reuses_it(self):
        extra = self.base / "final/contact_sheet.png"
        extra.write_bytes(b"not an upload image")
        first = self.deliver()
        output = Path(first["output_dir"])
        self.assertEqual(output.name, "images-v001")
        self.assertEqual({path.name for path in output.iterdir()}, {"a.jpg", "b.jpg"})
        self.assertEqual(first["copied_files"], 2)
        self.assertEqual(extra.read_bytes(), b"not an upload image")
        for image in first["images"]:
            self.assertEqual(file_hash(Path(image["path"])), image["sha256"])
            self.assertNotEqual(Path(image["path"]).stat().st_ino, (self.base / "final" / image["filename"]).stat().st_ino)
        with patch("lc_delivery.shutil.copy2", side_effect=AssertionError("Identical directory must be reused")):
            second = self.deliver()
        self.assertEqual(second["output_dir"], first["output_dir"])
        self.assertTrue(second["reused"])
        self.assertEqual(second["copied_files"], 0)
        self.assertFalse(list(self.base.rglob("*.zip")))

    def test_legacy_scattered_outputs_flatten_without_filename_collisions(self):
        for job in self.manifest["jobs"]:
            folder = self.base / "legacy" / job["id"]
            folder.mkdir(parents=True)
            target = folder / "image.jpg"
            (self.base / job["final_output"]).rename(target)
            job["final_output"] = str(target.relative_to(self.base))
        result = self.deliver()
        self.assertEqual({image["filename"] for image in result["images"]}, {"a--image.jpg", "b--image.jpg"})
        self.assertTrue(all((self.base / job["final_output"]).is_file() for job in self.manifest["jobs"]))

    def test_optional_unapproved_and_held_images_are_not_exposed(self):
        self.manifest["jobs"].append({"id": "optional", "required": False, "status": "pending", "final_output": "final/stale.jpg"})
        (self.base / "final/stale.jpg").write_bytes(b"unapproved stale output")
        result = self.deliver()
        self.assertEqual(result["image_count"], 2)
        self.assertNotIn("stale.jpg", {image["filename"] for image in result["images"]})
        self.manifest["jobs"][0]["hold"] = True
        with self.assertRaisesRegex(ValueError, "required image"):
            self.deliver()

    def test_gate_and_current_qa_bytes_are_required(self):
        for gate in (None, {}, {"ready": False}, {"ready": True, "project_id": "other"}):
            with self.assertRaises(ValueError):
                delivery.prepare_delivery_directory(self.manifest, self.base, delivery_result=gate)
        (self.base / "final/a.jpg").write_bytes(b"changed after review")
        with self.assertRaisesRegex(ValueError, "changed after QA"):
            self.deliver()
        self.assertFalse((self.base / "delivery").exists())

    def test_existing_user_directory_or_marker_is_never_overwritten(self):
        (self.base / "final/notes.txt").write_text("user notes")
        root = self.base / "delivery"
        occupied = root / "images-v001"
        occupied.mkdir(parents=True)
        (occupied / "keep.txt").write_text("user-owned")
        (root / ".images-v002.json").write_text("user-owned marker name")
        result = self.deliver()
        self.assertEqual(Path(result["output_dir"]).name, "images-v003")
        self.assertEqual((occupied / "keep.txt").read_text(), "user-owned")
        self.assertEqual((root / ".images-v002.json").read_text(), "user-owned marker name")

    def test_modified_prior_delivery_is_preserved_and_gets_new_version(self):
        (self.base / "final/notes.txt").write_text("user notes")
        first = self.deliver()
        modified = Path(first["output_dir"]) / "a.jpg"
        modified.write_bytes(b"user modified archived delivery")
        second = self.deliver()
        self.assertNotEqual(first["output_dir"], second["output_dir"])
        self.assertEqual(modified.read_bytes(), b"user modified archived delivery")
        self.assertEqual(second["copied_files"], 2)

    def test_symlink_sources_and_output_roots_are_rejected(self):
        source = self.base / "final/a.jpg"
        source.unlink()
        source.symlink_to(self.base / "final/b.jpg")
        with self.assertRaisesRegex(ValueError, "Symlink"):
            self.deliver()
        source.unlink()
        source.write_bytes(b"approved synthetic fixture a")
        (self.base / "final/notes.txt").write_text("extra")
        (self.base / "delivery").symlink_to(self.base / "final", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "Symlink"):
            self.deliver()

    def test_copy_failure_does_not_publish_a_partial_directory(self):
        (self.base / "final/notes.txt").write_text("extra")
        original = delivery.shutil.copy2
        def failing(source, target):
            if Path(source).name == "b.jpg":
                raise OSError("synthetic copy failure")
            return original(source, target)
        with patch("lc_delivery.shutil.copy2", side_effect=failing), self.assertRaisesRegex(OSError, "copy failure"):
            self.deliver()
        self.assertFalse(list((self.base / "delivery").glob("images-v*")))
        self.assertFalse(list((self.base / "delivery").glob(".images-stage-*")))
        self.assertTrue((self.base / "final/a.jpg").is_file())

    def test_filesystems_without_hardlinks_use_exclusive_copy_fallback(self):
        (self.base / "final/notes.txt").write_text("extra")
        with patch("lc_delivery.os.link", side_effect=OSError("Links unsupported")):
            result = self.deliver()
        self.assertEqual(result["image_count"], 2)
        for image in result["images"]:
            self.assertEqual(file_hash(Path(image["path"])), image["sha256"])

    def test_source_mutation_during_copy_rejects_delivery(self):
        (self.base / "final/notes.txt").write_text("extra")
        original = delivery.shutil.copy2
        def changing(source, target):
            value = original(source, target)
            if Path(source).name == "b.jpg":
                (self.base / "final/a.jpg").write_bytes(b"concurrent source replacement")
            return value
        with patch("lc_delivery.shutil.copy2", side_effect=changing), self.assertRaisesRegex(ValueError, "final changed while"):
            self.deliver()
        self.assertFalse(list((self.base / "delivery").glob("images-v*")))

    def test_user_file_at_delivery_root_is_preserved(self):
        (self.base / "final/notes.txt").write_text("extra")
        (self.base / "delivery").write_text("user-owned root file")
        with self.assertRaisesRegex(ValueError, "occupied"):
            self.deliver()
        self.assertEqual((self.base / "delivery").read_text(), "user-owned root file")

    def test_concurrent_directory_delivery_copies_once(self):
        (self.base / "final/notes.txt").write_text("extra")
        context = multiprocessing.get_context("spawn")
        release, outcomes = context.Event(), context.Queue()
        processes = [context.Process(target=_delivery_worker, args=(str(self.base), self.manifest, release, outcomes)) for _ in range(2)]
        try:
            for process in processes:
                process.start()
            release.set()
            results = [outcomes.get(timeout=20) for _ in processes]
            for process in processes:
                process.join(10)
                self.assertEqual(process.exitcode, 0)
            self.assertFalse(any("error" in result for result in results), results)
            self.assertEqual(len({result["output_dir"] for result in results}), 1)
            self.assertEqual(sorted(result["copied_files"] for result in results), [0, 2])
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                process.join(10)

    def test_compaction_returns_its_verified_after_gate(self):
        import test_lc_delivery as fixtures
        fixture = fixtures.CompactDeliveryTests()
        fixture.setUp()
        try:
            with patch.object(fixture, "gate", wraps=fixture.gate) as gate:
                result = fixture.compact()
            self.assertEqual(gate.call_count, 2)
            self.assertEqual(result["delivery_result"], {"ready": True})
        finally:
            fixture.tearDown()


class ScopedSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lc-scoped-snapshot-")
        self.base = Path(self.temp.name).resolve()
        self.manifest_path = self.base / "project_manifest.json"
        self.manifest = {"project_id": "snapshot-fixture", "test_fixture": True, "references": [{"id": "product", "path": "source/product.png",
            "quality_metrics": {"product_crop_path": "review/source_quality/product.png", "detail_regions": [{"path": "review/source_quality/detail.png"}],
                "target_previews": [{"job_id": key, "path": f"review/source_quality/{key}-target.png"} for key in ("a", "b")]}}],
            "jobs": [{"id": key, "status": "generated", "render_mode": "reference_generate", "raw_output": f"raw/{key}.png", "final_output": f"final/{key}.jpg"} for key in ("a", "b")]}
        self.manifest["jobs"][1].update(background_asset="revision/backdrop.png", product_layers=[{"asset_path": "revision/layer.png", "mask_path": "revision/mask.png"}],
                                          layout={"items": [{"image": "revision/detail.png"}]})
        self.files = {"source/product.png", "review/source_quality/product.png", "review/source_quality/detail.png",
                      "review/source_quality/a-target.png", "review/source_quality/b-target.png", "revision/backdrop.png", "revision/layer.png", "revision/mask.png", "revision/detail.png",
                      "raw/a.png", "raw/b.png", "final/a.jpg", "final/b.jpg", "review/layouts/a.png", "review/layouts/b.png",
                      "review/submissions/a-proof.json", "review/submissions/b-proof.json", "user-notes.txt", "revision/unregistered.png"}
        for relative in self.files:
            path = self.base / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(("synthetic " + relative).encode())
        transactions._atomic(self.base / "review/source_quality/index.json", transactions._bytes({"entries": {"preview_a": {"path": "a-target.png"}, "preview_b": {"path": "b-target.png"}}}))
        transactions._atomic(self.base / "review/source_quality/review.json", transactions._bytes({"references": self.manifest["references"]}))
        transactions._atomic(self.base / "qa_report.json", transactions._bytes({"jobs": []}))
        transactions._atomic(self.manifest_path, transactions._bytes(self.manifest))

    def tearDown(self):
        self.temp.cleanup()

    def test_single_job_stages_validation_inputs_shared_metadata_and_own_artifacts(self):
        expected = {"source/product.png", "revision/backdrop.png", "revision/layer.png", "revision/mask.png", "revision/detail.png", "review/source_quality/product.png",
                    "review/source_quality/detail.png", "review/source_quality/a-target.png", "raw/a.png", "final/a.jpg", "review/layouts/a.png", "review/submissions/a-proof.json"}
        omitted = {"raw/b.png", "final/b.jpg", "review/layouts/b.png", "review/submissions/b-proof.json", "review/source_quality/b-target.png", "user-notes.txt", "revision/unregistered.png"}
        def operation(staged):
            for relative in expected:
                self.assertTrue((staged.parent / relative).is_file(), relative)
                self.assertNotEqual((staged.parent / relative).stat().st_ino, (self.base / relative).stat().st_ino)
            for relative in omitted:
                self.assertFalse((staged.parent / relative).exists(), relative)
            index = json.loads((staged.parent / "review/source_quality/index.json").read_text())
            self.assertIn("preview_b", index["entries"])
            self.assertTrue((staged.parent / "qa_report.json").is_file())
            return 0
        transactions.run_staged_command(self.manifest_path, ["a"], operation, command_name="prepare")
        self.assertTrue(all((self.base / relative).exists() for relative in omitted))
        journal = json.loads(next((self.base / transactions._AREA).glob("*/journal.json")).read_text())
        self.assertLess(journal["metrics"]["staged_files"], len(self.files))

    def test_unselected_real_validation_asset_is_cas_checked(self):
        def operation(staged):
            (self.base / "revision/mask.png").write_bytes(b"concurrent real input update")
            return 0
        with self.assertRaisesRegex(transactions.TransactionConflict, "input artifact changed"):
            transactions.run_staged_command(self.manifest_path, ["a"], operation, command_name="prepare")

    def test_another_jobs_output_is_included_only_when_used_as_real_input(self):
        self.manifest["jobs"][0]["layout"] = {"items": [{"image": "final/b.jpg"}]}
        actual = transactions._stage_project_files(self.manifest, self.base, {"a"}, command_name="prepare")
        self.assertIn("final/b.jpg", actual)
        self.assertNotIn("raw/b.png", actual)

    def test_malformed_asset_containers_are_left_to_manifest_validation(self):
        for invalid in (7, None, "not a list", {"path": "not-a-list.png"}):
            for field in ("product_layers", "disclosure_extra_images"):
                manifest = copy.deepcopy(self.manifest)
                manifest["jobs"][1][field] = invalid
                self.assertIn("raw/a.png", transactions._stage_project_files(manifest, self.base, {"a"}, command_name="prepare"))
            for field in ("items", "panels"):
                manifest = copy.deepcopy(self.manifest)
                manifest["jobs"][1]["layout"][field] = invalid
                self.assertIn("raw/a.png", transactions._stage_project_files(manifest, self.base, {"a"}, command_name="prepare"))
            manifest = copy.deepcopy(self.manifest)
            manifest["references"][0]["quality_metrics"]["target_previews"] = invalid
            manifest["critical_details"] = invalid
            self.assertIn("raw/a.png", transactions._stage_project_files(manifest, self.base, {"a"}, command_name="prepare"))
        manifest = copy.deepcopy(self.manifest)
        manifest["references"][0]["quality_metrics"]["target_previews"] = [{"job_id": [], "path": "user-notes.txt"}]
        manifest["critical_details"] = [{"id": "detail", "reference_crops": 7}]
        self.assertNotIn("user-notes.txt", transactions._stage_project_files(manifest, self.base, {"a"}, command_name="prepare"))


if __name__ == "__main__":
    unittest.main()
