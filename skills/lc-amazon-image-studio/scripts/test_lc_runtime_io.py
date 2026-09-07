"""Content-bound IO reuse; fixtures never authorize production observations."""
from __future__ import annotations

import copy
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

import lc_assets as assets
import lc_image_pipeline as pipeline
import lc_quality as quality
from pipeline_test_support import create_v3_fixture, MAIN_ID, SECONDARY_ID


class RuntimeIOTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()

    def test_repeated_hash_uses_one_read_only_within_scope(self):
        path = self.base / "source.bin"
        path.write_bytes(b"verified input")
        original = Path.open
        reads = []
        def opened(target, *args, **kwargs):
            if target == path and args == ("rb",):
                reads.append(target)
            return original(target, *args, **kwargs)
        with mock.patch.object(Path, "open", opened):
            with assets.file_hash_context():
                expected = assets.file_hash(path)
                with assets.file_hash_context():
                    self.assertEqual(expected, assets.file_hash(path))
                self.assertEqual(len(reads), 1)
                with assets.file_hash_context(fresh=True):
                    self.assertEqual(expected, assets.file_hash(path))
                self.assertEqual(len(reads), 2)
            self.assertEqual(expected, assets.file_hash(path))
        self.assertEqual(len(reads), 3)

    def test_same_size_and_restored_mtime_does_not_hide_source_change(self):
        path = self.base / "source.bin"
        path.write_bytes(b"old pixels")
        stat = path.stat()
        with assets.file_hash_context():
            first = assets.file_hash(path)
            path.write_bytes(b"new pixels")
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            self.assertNotEqual(first, assets.file_hash(path))

    def test_replace_and_symlink_retarget_invalidate_scope(self):
        path, replacement, link = (self.base / name for name in ("a", "b", "link"))
        path.write_bytes(b"first")
        replacement.write_bytes(b"other")
        link.symlink_to(path)
        with assets.file_hash_context():
            first = assets.file_hash(link)
            link.unlink()
            link.symlink_to(replacement)
            self.assertNotEqual(first, assets.file_hash(link))
            replacement.replace(path)
            self.assertNotEqual(first, assets.file_hash(path))

    def test_content_changed_while_reading_is_rejected(self):
        path = self.base / "source.bin"
        path.write_bytes(b"first")
        original = hashlib.sha256
        class ChangingHasher:
            def __init__(self):
                self.actual = original()
            def update(self, chunk):
                self.actual.update(chunk)
                path.write_bytes(b"other")
            def hexdigest(self):
                return self.actual.hexdigest()
        with mock.patch.object(assets.hashlib, "sha256", ChangingHasher):
            with self.assertRaisesRegex(ValueError, "changed while hashing"):
                assets.file_hash(path)

    def project(self):
        manifest = create_v3_fixture(self.base)
        for job in manifest["jobs"]:
            job["product_layers"] = []
        wide = copy.deepcopy(manifest["jobs"][1])
        wide.update(id="03_wide", kind="a_plus", canvas=[1940, 1200])
        manifest["jobs"].append(wide)
        return manifest

    def test_one_source_decode_serves_crops_and_all_canvas_previews(self):
        manifest = self.project()
        source = (self.base / manifest["references"][0]["path"]).resolve()
        opened, original = [], Image.open
        def tracked(path, *args, **kwargs):
            if isinstance(path, (str, Path)) and Path(path).resolve() == source:
                opened.append(path)
            return original(path, *args, **kwargs)
        with mock.patch.object(Image, "open", tracked):
            quality.assess_sources(manifest, self.base)
            self.assertEqual(len(opened), 1)
            snapshot = copy.deepcopy(manifest)
            quality.assess_sources(manifest, self.base)
            self.assertEqual(len(opened), 1)
        self.assertEqual(snapshot, manifest)
        self.assertEqual(len(manifest["references"][0]["quality_metrics"]["target_previews"]), 3)

    def test_selected_source_assessment_preserves_sibling_metadata_and_order(self):
        manifest = self.project()
        quality.assess_sources(manifest, self.base)
        before = copy.deepcopy(manifest)
        with mock.patch.object(Image, "open", side_effect=AssertionError("cache hit must not decode")):
            quality.assess_sources(manifest, self.base, job_ids={SECONDARY_ID})
            quality.assess_sources(manifest, self.base, job_ids={MAIN_ID})
        self.assertEqual(manifest, before)

    def test_cached_details_avoid_decode_and_tamper_rebuilds_exact_pixels(self):
        manifest = self.project()
        quality.assess_sources(manifest, self.base)
        pipeline.extract_detail_references(manifest, self.base)
        before = copy.deepcopy(manifest["critical_details"])
        crop = self.base / before[0]["reference_crops"][0]["path"]
        original_bytes = crop.read_bytes()
        with mock.patch.object(Image, "open", side_effect=AssertionError("cache hit must not decode")):
            pipeline.extract_detail_references(manifest, self.base)
        self.assertEqual(before, manifest["critical_details"])
        crop.write_bytes(b"modified preview")
        pipeline.extract_detail_references(manifest, self.base)
        self.assertEqual(crop.read_bytes(), original_bytes)
        self.assertEqual(before, manifest["critical_details"])

    def test_changed_detail_coordinates_invalidate_only_that_crop(self):
        manifest = self.project()
        quality.assess_sources(manifest, self.base)
        pipeline.extract_detail_references(manifest, self.base)
        before = copy.deepcopy(manifest["critical_details"])
        manifest["critical_details"][0]["locations"][0]["bbox_in_product_norm"][0] -= .1
        pipeline.extract_detail_references(manifest, self.base)
        after = manifest["critical_details"]
        self.assertNotEqual(before[0]["reference_crops"][0]["cache_key"], after[0]["reference_crops"][0]["cache_key"])
        self.assertEqual(before[1], after[1])

    def test_crop_algorithm_version_invalidates_cache_without_rekeying_legacy_v1(self):
        manifest = self.project()
        quality.assess_sources(manifest, self.base)
        pipeline.extract_detail_references(manifest, self.base)
        before = copy.deepcopy(manifest["critical_details"])
        with mock.patch.object(pipeline, "DETAIL_CROP_ALGORITHM_VERSION", 2), \
                mock.patch.object(Image, "open", wraps=Image.open) as opened:
            pipeline.extract_detail_references(manifest, self.base)
        self.assertEqual(opened.call_count, 1)
        for old, new in zip(before, manifest["critical_details"]):
            self.assertNotEqual(old["reference_crops"][0]["cache_key"], new["reference_crops"][0]["cache_key"])
            self.assertEqual(old["reference_crops"][0]["sha256"], new["reference_crops"][0]["sha256"])
        pipeline.extract_detail_references(manifest, self.base)
        self.assertEqual(before, manifest["critical_details"])


if __name__ == "__main__":
    unittest.main()
