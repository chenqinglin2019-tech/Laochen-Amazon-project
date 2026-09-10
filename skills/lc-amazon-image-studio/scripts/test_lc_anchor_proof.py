"""Real review workflow on marked synthetic fixtures; no production approvals."""
import copy
import tempfile
import unittest
from pathlib import Path

import lc_image_pipeline as p
import lc_scheduler as s
import lc_workflow as w
from pipeline_test_support import (SECONDARY_ID, NOTE, create_v3_fixture,
                                   prepare_fixture, simulate_secondary_output)


class AnchorProofTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lc-anchor-proof-fixture-")
        self.base = Path(self.temp.name)
        self.m = create_v3_fixture(self.base)
        self.m["review_dependency_version"] = 2
        prepare_fixture(self.m, self.base)
        simulate_secondary_output(self.m, self.base)
        job = p.find_by_id(self.m["jobs"], SECONDARY_ID)
        result = w.review_prepare(self.m, self.base, SECONDARY_ID,
            {"raw_product_bbox_norm": job["target_product_bbox_norm"],
             "detail_output_bbox_norms": job["fixture_output_detail_boxes"]})
        packet = p.read_json(Path(result["packet"]))
        for field in ("semantic_qa_results", "policy_qa_results", "detail_qa_results"):
            for key in packet["reviews"][field]:
                packet["reviews"][field][key] = {"verdict": "pass", "notes": NOTE}
        packet["reviews"]["ai_disclosure"] = {"human_source": "none", "notes": NOTE}
        self.assertEqual(w.review_submit(self.m, self.base, packet)["status"], "qa_passed")
        self.m["anchor_job_id"] = SECONDARY_ID
        self.m["scheduler_policy"] = s.default_policy()

    def tearDown(self):
        self.temp.cleanup()

    @property
    def job(self):
        return p.find_by_id(self.m["jobs"], SECONDARY_ID)

    def test_true_submission_survives_local_encoding_repair_and_missing_cache(self):
        self.assertTrue(s.anchor_passed(self.m, self.base))
        self.job["status"] = "export_repair_needed"
        self.job.setdefault("export", {})["jpeg_quality"] = 95
        image = self.base / "review/image_layers" / f"{SECONDARY_ID}.png"
        image.unlink()
        self.assertTrue(s.anchor_passed(self.m, self.base))
        self.assertFalse(s.anchor_passed(self.m))  # No filesystem proof without base.
        self.assertEqual(self.job["status"], "export_repair_needed")

    def test_generation_raw_evidence_annotations_and_submission_changes_fail_closed(self):
        changes = [
            lambda m: p.find_by_id(m["jobs"], SECONDARY_ID).update(composition="changed perspective"),
            lambda m: m["product_truth"].update(product="different product"),
            lambda m: p.find_by_id(m["jobs"], SECONDARY_ID).update(raw_product_bbox_norm=[0, 0, 1, 1]),
            lambda m: m["references"][0]["quality_review"].update(clarity="unknown"),
            lambda m: p.find_by_id(m["jobs"], SECONDARY_ID).update(status="generation_repair_needed"),
        ]
        for change in changes:
            with self.subTest(change=change):
                candidate = copy.deepcopy(self.m)
                change(candidate)
                self.assertFalse(s.anchor_passed(candidate, self.base))
        for path in (self.base / self.job["raw_output"], self.base / self.m["references"][0]["path"],
                     self.base / self.job["product_review_proof"]["path"]):
            original = path.read_bytes()
            path.write_bytes(original + b"modified synthetic fixture")
            self.assertFalse(s.anchor_passed(self.m, self.base))
            path.write_bytes(original)
            self.assertTrue(s.anchor_passed(self.m, self.base))

    def test_legacy_status_fallback_verifies_real_final_and_current_qa(self):
        self.job.pop("product_review_proof")
        self.assertTrue(s.anchor_passed(self.m, self.base))
        final = self.base / self.job["final_output"]
        final.write_bytes(final.read_bytes() + b"modified synthetic final")
        self.assertFalse(s.anchor_passed(self.m, self.base))
        self.assertTrue(s.anchor_passed(self.m))  # Historical no-base API unchanged.


if __name__ == "__main__":
    unittest.main()
