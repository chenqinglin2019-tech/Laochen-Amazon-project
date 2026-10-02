"""A frozen product image may support product comparison, never right status."""
import hashlib
from pathlib import Path
import tempfile
import unittest

from assessment_estimate import product_image_index, _substantive_refs
from necessary_completion import _reviewed_fact_limitations


class ProductImageReviewRefsTests(unittest.TestCase):
    def test_hash_bound_image_reference_is_product_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image = root / "main.jpg"
            image.write_bytes(b"offline product image")
            row = {"image_id": "IMG-001", "path": str(image),
                   "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                   "bytes": image.stat().st_size}
            registry = product_image_index({"images": [row]}, root)
            self.assertEqual(registry["IMG-001"]["provider"], "product")
            self.assertEqual(_substantive_refs(["IMG-001"], registry, {}), set())
            image.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "HASH_MISMATCH"):
                product_image_index({"images": [row]}, root)

    def test_duplicate_or_unbound_image_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image = root / "main.jpg"
            image.write_bytes(b"image")
            row = {"image_id": "IMG-001", "path": str(image),
                   "sha256": hashlib.sha256(image.read_bytes()).hexdigest(), "bytes": 5}
            with self.assertRaisesRegex(ValueError, "PRODUCT_IMAGE_EVIDENCE_INVALID"):
                product_image_index({"images": [row, row]}, root)
            with self.assertRaisesRegex(ValueError, "BYTES_MISMATCH"):
                product_image_index({"images": [{**row, "bytes": 6}]}, root)

    def test_reviewed_unknown_with_product_image_becomes_explicit_limit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image = root / "main.jpg"
            image.write_bytes(b"image")
            task = {"assessment_revision": "known-findings-risk-v1", "images": [{
                "image_id": "IMG-001", "path": str(image),
                "sha256": hashlib.sha256(image.read_bytes()).hexdigest(), "bytes": 5}]}
            assessment = {"assessments": [{"scenario_id": "S", "jurisdiction": "US",
                "right_type": "utility_model", "assessment_status": "pending", "risk": None,
                "right_state": "unknown", "pending_reasoning": "制度依据待核。",
                "evidence_refs": ["IMG-001"],
                "review_resolution": {"method": "independent_agreement"}}]}
            limits = _reviewed_fact_limitations(assessment,
                {"collections": {}, "source_runs": []}, evidence_root=root, task=task)
            self.assertEqual(len(limits), 1)
            self.assertEqual(limits[0]["kind"], "reviewed_scope_gap")
            self.assertEqual(limits[0]["evidence_refs"], ["IMG-001"])

    def test_pending_candidate_with_exact_retained_original_gets_limit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original = root / "application.txt"
            original.write_text("Published application claim text")
            evidence_id = "EV-ORIGINAL"
            record = {"evidence_id": evidence_id, "candidate_id": "CAND-A1",
                "jurisdiction": "US", "kind": "patent_document",
                "path": str(original), "sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
                "bytes": original.stat().st_size, "checked_at": "2026-09-29T00:00:00Z",
                "source_url": "https://example.org/application"}
            row = {"scenario_id": "S", "jurisdiction": "US", "right_type": "patent",
                "candidate_id": "CAND-A1", "assessment_status": "pending", "risk": None,
                "pending_reasoning": "当前结构未知。", "evidence_refs": [evidence_id]}
            assessment = {"assessments": [row], "supplement": {
                "schema": "IPR-SUPPLEMENT/1.0", "evidence": [record], "coverage_notes": []}}
            limits = _reviewed_fact_limitations(assessment,
                {"collections": {}, "source_runs": []}, evidence_root=root, task={})
            self.assertEqual(len(limits), 1)
            self.assertEqual(limits[0]["kind"], "reviewed_fact_limit")
            self.assertEqual(limits[0]["evidence_refs"], [evidence_id])


if __name__ == "__main__":
    unittest.main()
