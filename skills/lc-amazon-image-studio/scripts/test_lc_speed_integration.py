"""No model/account access: production flow invariants on synthetic fixtures."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import lc_cli_output as output
import lc_image_pipeline as p
import lc_project_contracts as contracts
import lc_review_rules as rules
import lc_workflow as w
from pipeline_test_support import create_v3_fixture, ready_fixture, SECONDARY_ID, MAIN_ID, prepare_fixture


class SpeedIntegrationTests(unittest.TestCase):
    def test_bad_background_mask_blocks_only_main_and_does_not_call_model(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            manifest = ready_fixture(base)
            main = p.find_by_id(manifest["jobs"], MAIN_ID)
            peer = p.find_by_id(manifest["jobs"], SECONDARY_ID)
            peer["status"] = "pending"
            main["background_normalization"] = {"version": 1, "reviewed": True,
                "protection_covers_product_and_shadow": True, "source_pixel_sha256": "0" * 64,
                "background_mask": {"path": "source/missing-background.png", "sha256": "1" * 64},
                "protection_mask": {"path": "source/missing-protection.png", "sha256": "2" * 64}}
            manifest["anchor_job_id"] = MAIN_ID
            p.prepare(manifest, base)
            self.assertEqual(main["status"], "blocked")
            self.assertTrue(main["blocked_reason"].startswith("LOCAL_BACKGROUND:"))
            self.assertEqual(manifest["generation_gate"]["status"], "open")
            self.assertIn(SECONDARY_ID, [item["id"] for item in p.execution_plan(manifest, base)["dispatch"]])
            del main["background_normalization"]
            p.prepare(manifest, base, [MAIN_ID])
            self.assertNotEqual(main["status"], "blocked")

    def test_status_is_readonly_even_with_recovery_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            manifest = create_v3_fixture(base)
            # A status request must not create a lock, recover or rewrite even
            # an unprepared project. Its output is observation, not admission.
            (base / ".lc-transactions").mkdir()
            before = {str(path.relative_to(base)): (path.stat().st_mtime_ns, path.read_bytes())
                      for path in base.rglob("*") if path.is_file()}
            run = subprocess.run([sys.executable, str(p.SCRIPT_DIR / "lc_image_pipeline.py"),
                                  "status", "--manifest", str(base / "project_manifest.json"), "--json"],
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(json.loads(run.stdout)["image_count"], len(manifest["jobs"]))
            after = {str(path.relative_to(base)): (path.stat().st_mtime_ns, path.read_bytes())
                     for path in base.rglob("*") if path.is_file()}
            self.assertEqual(before, after)

    def test_single_image_copy_defect_does_not_fail_peer_contract(self):
        manifest = {"copy_budget": contracts.default_copy_budget(), "jobs": [
            {"id": "bad", "kind": "listing", "layout": {"headline": " ".join(["Long"] * 40)}},
            {"id": "good", "kind": "listing", "layout": {"headline": "Useful Detail"}}]}
        self.assertFalse(contracts.project_contract_report(manifest)["passed"])
        self.assertFalse(contracts.project_contract_report(manifest, ["bad"])["passed"])
        self.assertTrue(contracts.project_contract_report(manifest, ["good"])["passed"])
        self.assertEqual(contracts.project_contract_report(manifest)["shared_issues"], [])

    def test_scoped_qa_packet_and_product_ignore_cli_body_not_quality(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            manifest = ready_fixture(base)
            manifest["review_rule_profile"] = "scoped_v1"
            job = p.find_by_id(manifest["jobs"], SECONDARY_ID)
            job["claim_ids"] = ["port_count"]
            def contexts():
                return (p.qa_fingerprint(manifest, job, base), w.review_context(manifest, job, base),
                        w.product_review_context(manifest, job, base))
            original = rules._read_source
            before = contexts()
            def cli_changed(name):
                source = original(name)
                return source.replace('def main() -> int:', 'def main() -> int:\n    """Different CLI log wording."""') if name == "lc_image_pipeline.py" else source
            with patch.object(rules, "_read_source", side_effect=cli_changed):
                self.assertEqual(before, contexts())
            def qa_changed(name):
                source = original(name)
                return source.replace('def qa_fingerprint(manifest: dict, job: dict, base: Path) -> str:',
                                      'def qa_fingerprint(manifest: dict, job: dict, base: Path) -> str:\n    """Changed visual rule."""') if name == "lc_image_pipeline.py" else source
            with patch.object(rules, "_read_source", side_effect=qa_changed):
                self.assertTrue(all(a != b for a, b in zip(before, contexts())))
            manifest["facts"][0]["text"] = "Changed real fact"
            self.assertTrue(all(a != b for a, b in zip(before, contexts())))

    def test_image_objects_never_enter_text_even_in_detailed_results(self):
        value = {"content": [{"type": "image", "data": "secret-raster-base64", "mimeType": "image/png"}],
                 "image_url": "data:image/png;base64,YWJjZGVm", "b64_json": "secret", "path": "/tmp/output.png"}
        encoded = json.dumps(output.safe_text_payload(value))
        self.assertNotIn("secret", encoded)
        self.assertNotIn("YWJj", encoded)
        self.assertIn("/tmp/output.png", encoded)

    def test_unknown_profile_fails_validation_not_type_error(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = create_v3_fixture(Path(directory))
            manifest["review_rule_profile"] = []
            self.assertIn("review_rule_profile", " ".join(p.validate_manifest(manifest, Path(directory))))

    def test_status_invalid_manifest_returns_structured_error_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            path = base / "project_manifest.json"
            p.write_json(path, {"jobs": "invalid"})
            before = (path.stat().st_mtime_ns, path.read_bytes())
            run = subprocess.run([sys.executable, str(p.SCRIPT_DIR / "lc_image_pipeline.py"),
                "status", "--manifest", str(path), "--json"], capture_output=True, text=True)
            self.assertEqual(run.returncode, 2)
            self.assertFalse(json.loads(run.stdout)["ok"])
            self.assertNotIn("Traceback", run.stderr)
            self.assertEqual(before, (path.stat().st_mtime_ns, path.read_bytes()))


if __name__ == "__main__":
    unittest.main()
