"""Synthetic-fixture dependency migration proofs; never production approvals."""
import copy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image
import lc_image_pipeline as p
import lc_workflow as w
from lc_dependencies import migrate_dependencies, evidence_dependencies
from pipeline_test_support import MAIN_ID, SECONDARY_ID, NOTE, create_v3_fixture, prepare_fixture, ready_fixture


class DependencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lc-dependency-test-")
        self.base = Path(self.temp.name)
        self.m = create_v3_fixture(self.base)

    def tearDown(self):
        self.temp.cleanup()

    @property
    def job(self):
        return self.m["jobs"][1]

    def ingest_fixture(self):
        prepare_fixture(self.m, self.base)
        p.transition_job(self.m, SECONDARY_ID, "generating", NOTE, self.base)
        self.artifact = self.base / "fixture-artifact.png"
        Image.new("RGB", (1600, 1600), "white").save(self.artifact)
        w.ingest(self.m, self.base, SECONDARY_ID, self.artifact, self.job["active_attempt_id"])
        return copy.deepcopy(self.m)

    def change_sibling(self):
        self.m["critical_details"][0]["visibility"][MAIN_ID] = "optional"

    def test_evidence_closure_includes_claims_panels_layers_and_recursive_real_sources(self):
        self.m["references"].extend([
            {"id": "generated-panel", "path": "source/generated.png", "provenance": {"kind": "generated",
             "source_reference_ids": ["product_front"]}},
            {"id": "unrelated", "path": "source/unrelated.png"}])
        self.m["facts"].extend([
            {"id": "used-claim", "text": "Supported", "evidence": ["generated-panel"]},
            {"id": "unused-claim", "text": "Unrelated", "evidence": ["unrelated"]}])
        self.job["claim_ids"] = ["used-claim"]
        self.job["layout"] = {"panels": [{"reference_id": "generated-panel", "evidence_refs": ["used-claim"]}]}
        self.job["product_layers"] = [{"source_binding": {"source_reference_hashes": {"product_front": "fixture"}}}]
        deps = evidence_dependencies(self.m, self.job, self.base)
        self.assertEqual({r["id"] for r in deps["references"]}, {"product_front", "generated-panel"})
        self.assertEqual([f["id"] for f in deps["facts"]], ["used-claim"])
        self.assertEqual(next(r for r in deps["references"] if r["id"] == "generated-panel")["actual_sha256"], "MISSING")
        self.assertTrue(all(set(d["visibility"]) == {SECONDARY_ID} for d in deps["details"]))
        self.m["facts"][-1]["text"] = "Changed unused claim"
        self.m["references"][-1]["quality_review"] = {"changed": True}
        self.assertEqual(deps, evidence_dependencies(self.m, self.job, self.base))
        self.m["facts"][-2]["text"] = "Changed used claim"
        self.assertNotEqual(deps, evidence_dependencies(self.m, self.job, self.base))

    def test_closure_binds_actual_pixels_shared_truth_and_missing_links(self):
        baseline = evidence_dependencies(self.m, self.job, self.base)
        Image.new("RGB", (100, 100), "red").save(self.base / "source/product_front.png")
        self.assertNotEqual(baseline, evidence_dependencies(self.m, self.job, self.base))
        changed_pixels = evidence_dependencies(self.m, self.job, self.base)
        self.m["product_truth"]["geometry_lock"]["locked_structure"] = ["different physical shape"]
        self.assertNotEqual(changed_pixels, evidence_dependencies(self.m, self.job, self.base))
        self.job["source_reference_ids"].append("missing-reference")
        self.assertIn("missing-reference", evidence_dependencies(self.m, self.job, self.base)["missing"])

    def test_shared_source_diagnostic_previews_do_not_bind_other_jobs(self):
        self.m["references"][0]["quality_metrics"] = {"target_previews": [{"job_id": MAIN_ID, "path": "old.png"}]}
        before = evidence_dependencies(self.m, self.job, self.base)
        self.m["references"][0]["quality_metrics"]["target_previews"][0]["path"] = "new.png"
        self.m["references"][0]["quality_metrics"]["detail_regions"] = [{"detail_id": "unused-detail"}]
        self.assertEqual(before, evidence_dependencies(self.m, self.job, self.base))
        self.m["references"][0]["quality_review"]["notes"] = "Changed actual source judgment"
        self.assertNotEqual(before, evidence_dependencies(self.m, self.job, self.base))

    def test_scoped_review_ignores_unused_fact_but_tracks_bound_claim(self):
        self.m = ready_fixture(self.base)
        self.m["review_dependency_version"] = 2
        self.job["claim_ids"] = ["port_count"]
        self.m["facts"].append({"id": "unrelated", "text": "Unrelated fact", "evidence": ["product_front"]})
        context = w.review_context(self.m, self.job, self.base)
        self.m["facts"][-1]["text"] = "Changed unrelated fact"
        self.assertEqual(context, w.review_context(self.m, self.job, self.base))
        self.m["facts"][0]["text"] = "Changed bound fact"
        self.assertNotEqual(context, w.review_context(self.m, self.job, self.base))

    def test_scoped_generation_qa_and_review_context_ignore_sibling_visibility(self):
        self.m = ready_fixture(self.base)
        self.job["generation_dependency_version"] = 2
        fingerprints = p.current_fingerprints(self.m, self.job, self.base)
        qa, context = p.qa_fingerprint(self.m, self.job, self.base), w.review_context(self.m, self.job, self.base)
        self.change_sibling()
        self.assertEqual(fingerprints, p.current_fingerprints(self.m, self.job, self.base))
        self.assertEqual(qa, p.qa_fingerprint(self.m, self.job, self.base))
        self.assertEqual(context, w.review_context(self.m, self.job, self.base))
        self.m["critical_details"][0]["visibility"][SECONDARY_ID] = "optional"
        self.assertNotEqual(fingerprints["generation"], p.current_fingerprints(self.m, self.job, self.base)["generation"])

    def test_legacy_fingerprint_is_unchanged_until_explicit_opt_in(self):
        prepare_fixture(self.m, self.base)
        before = p.current_fingerprints(self.m, self.job, self.base)["generation"]
        self.job["generation_dependency_version"] = 1
        self.assertEqual(before, p.current_fingerprints(self.m, self.job, self.base)["generation"])
        self.change_sibling()
        self.assertNotEqual(before, p.current_fingerprints(self.m, self.job, self.base)["generation"])

    def test_reconstructed_view_proves_recovery_and_preserves_ingest_idempotence(self):
        old = self.ingest_fixture()
        attempt = copy.deepcopy(self.job["generation_attempts"][0])
        raw = self.base / self.job["raw_output"]
        before = (p.sha256_file(raw), raw.stat().st_mtime_ns)
        self.change_sibling()
        p.compile_prompts(self.m, self.base, [SECONDARY_ID])
        self.assertEqual(self.job["status"], "pending")
        self.assertNotIn("generated_prompt_hash", self.job)
        result = migrate_dependencies(self.m, self.base, old, [SECONDARY_ID], source_kind="reconstructed_verified_dependency_view")
        self.assertEqual(result["model_calls"], 0)
        self.assertEqual(self.job["generation_dependency_version"], 2)
        self.assertEqual(self.job["status"], "generated")
        self.assertEqual(before, (p.sha256_file(raw), raw.stat().st_mtime_ns))
        self.assertEqual(attempt, self.job["generation_attempts"][0])
        self.assertEqual(self.job["metrics"]["model_dispatches"], 1)
        self.assertTrue(w.ingest(self.m, self.base, SECONDARY_ID, self.artifact, attempt["id"])["idempotent"])
        p.prepare(self.m, self.base, [SECONDARY_ID])
        self.assertEqual(self.job["generated_prompt_hash"], self.job["prompt_hash"])
        self.assertTrue(migrate_dependencies(self.m, self.base, old, [SECONDARY_ID])["jobs"][0]["cached"])

    def test_migration_rejects_unproven_view_changed_own_inputs_or_changed_raw(self):
        for failure in ("proof", "own", "raw"):
            with self.subTest(failure=failure):
                self.m = create_v3_fixture(self.base)
                old = self.ingest_fixture()
                if failure == "proof":
                    old["critical_details"][0]["visibility"][MAIN_ID] = "optional"
                elif failure == "own":
                    self.job["scene"] = "An unrelated changed scene"
                else:
                    Image.new("RGB", (1600, 1600), "red").save(self.base / self.job["raw_output"])
                before = copy.deepcopy(self.m)
                with self.assertRaises(p.PipelineError):
                    migrate_dependencies(self.m, self.base, old, [SECONDARY_ID], source_kind="reconstructed_verified_dependency_view")
                self.assertEqual(before, self.m)

    def test_cli_migration_records_source_proof_without_changing_sibling(self):
        old = self.ingest_fixture()
        self.change_sibling()
        p.compile_prompts(self.m, self.base, [SECONDARY_ID])
        sibling = copy.deepcopy(self.m["jobs"][0])
        manifest_path, proof_path = self.base / "project_manifest.json", self.base / "dependency-view.json"
        p.write_json(manifest_path, self.m)
        p.write_json(proof_path, old)
        command = [sys.executable, str(Path(p.__file__)), "migrate-dependencies", "--manifest", str(manifest_path),
                   "--source-manifest", str(proof_path), "--source-kind", "reconstructed_verified_dependency_view", "--jobs", SECONDARY_ID]
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.m = p.read_json(manifest_path)
        self.assertEqual(self.m["jobs"][0], sibling)
        record = self.job["dependency_migrations"][0]
        self.assertEqual(record["source_kind"], "reconstructed_verified_dependency_view")
        self.assertEqual(record["proof"]["kind"], "ingested_attempt")
        self.assertTrue((self.base / "review/dependency_migrations" / f"{record['source_view_sha256']}.json").is_file())

    def test_explicit_project_fork_keeps_all_artifact_and_input_proofs(self):
        old = self.ingest_fixture()
        source_id = old["project_id"]
        self.m["project_id"] = "fixture-retained-source-fork"
        before = copy.deepcopy(self.m)
        with self.assertRaisesRegex(p.PipelineError, "same project"):
            migrate_dependencies(self.m, self.base, old, [SECONDARY_ID])
        self.assertEqual(before, self.m)
        self.job["scene"] = "Changed same-image scene must not be authorized by a fork"
        with self.assertRaisesRegex(p.PipelineError, "scoped generation inputs changed"):
            migrate_dependencies(self.m, self.base, old, [SECONDARY_ID], allow_project_fork=True)
        self.m = before
        raw = self.base / self.job["raw_output"]
        raw_before = (p.sha256_file(raw), raw.stat().st_mtime_ns)
        manifest_path, source_path = self.base / "project_manifest.json", self.base / "retained-source.json"
        p.write_json(manifest_path, self.m)
        p.write_json(source_path, old)
        source_sha = p.sha256_file(source_path)
        result = subprocess.run([sys.executable, str(Path(p.__file__)), "migrate-dependencies", "--manifest", str(manifest_path),
            "--source-manifest", str(source_path), "--allow-project-fork", "--jobs", SECONDARY_ID],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.m = p.read_json(manifest_path)
        record = self.job["dependency_migrations"][0]
        self.assertEqual(record["source_project_id"], source_id)
        self.assertEqual(record["target_project_id"], self.m["project_id"])
        self.assertTrue(record["project_fork"])
        self.assertEqual(raw_before, (p.sha256_file(raw), raw.stat().st_mtime_ns))
        self.assertEqual(source_sha, p.sha256_file(source_path))


if __name__ == "__main__":
    unittest.main()
