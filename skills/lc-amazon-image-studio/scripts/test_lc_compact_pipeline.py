"""End-to-end local regression fixtures; no model calls or production approvals."""
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import lc_image_pipeline as p
import lc_delivery as delivery
from pipeline_test_support import (create_v3_fixture, prepare_fixture, simulate_secondary_output,
                                   finish_fixture, SECONDARY_ID, bind_source_reviews)


class CompactPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lc-compact-integration-")
        self.base = Path(self.temp.name).resolve()
        self.manifest = self.base / "project_manifest.json"

    def tearDown(self):
        self.temp.cleanup()

    def ready(self):
        m = create_v3_fixture(self.base)
        m["delivery_profile"] = {"name": "compact_jpg"}
        m["review_dependency_version"] = 2
        prepare_fixture(m, self.base)
        simulate_secondary_output(m, self.base)
        finish_fixture(m, self.base)
        return m

    def compact(self, m):
        return delivery.compact_project(m, self.base, manifest_path=self.manifest,
            delivery_check_fn=p.delivery_check, qa_fingerprint_fn=p.qa_fingerprint,
            stage_fingerprints_fn=p.current_fingerprints)

    def test_compact_delivery_recheck_and_no_change_never_render(self):
        m = self.ready()
        hashes = [j["final_sha256"] for j in m["jobs"]]
        result = self.compact(m)
        self.assertGreater(result["reclaimed_bytes"], 0)
        self.assertFalse(list((self.base / "review" / "layouts").glob("*.png")))
        self.assertTrue(all(j["final_output"].endswith(".jpg") for j in m["jobs"]))
        self.assertTrue(p.delivery_check(m, self.base)["ready"])
        with patch("lc_layout.render_batch", side_effect=AssertionError("unchanged compact project rendered")):
            p.prepare(m, self.base)
            p.aspect_safe_postprocess(m, self.base)
            p.quality_assurance(m, self.base)
            p.create_final_contact_sheet(m, self.base)
            self.assertTrue(p.delivery_check(m, self.base)["ready"])
        self.assertEqual(hashes, [j["final_sha256"] for j in m["jobs"]])
        self.assertFalse(list((self.base / "review" / "layouts").glob("*.png")))
        self.assertEqual([], self.compact(m)["removed"])

    def test_compact_still_rejects_tampered_final(self):
        m = self.ready()
        self.compact(m)
        with (self.base / m["jobs"][0]["final_output"]).open("ab") as stream:
            stream.write(b"changed")
        with self.assertRaises(p.PipelineError):
            p.delivery_check(m, self.base)

    def test_compact_single_export_change_keeps_sibling_and_rebuilds_overview(self):
        m = self.ready()
        self.compact(m)
        first, changed = m["jobs"]
        first_hash = first["final_sha256"]
        attempts = changed["metrics"]["model_dispatches"]
        changed["export"]["quality"] = 95
        p.prepare(m, self.base, [changed["id"]])
        p.aspect_safe_postprocess(m, self.base, job_ids=[changed["id"]])
        p.quality_assurance(m, self.base, [changed["id"]], update_overviews=True)
        p.create_final_contact_sheet(m, self.base)
        self.assertTrue(p.delivery_check(m, self.base)["ready"])
        self.assertEqual(first_hash, first["final_sha256"])
        self.assertEqual(attempts, changed["metrics"]["model_dispatches"])
        self.assertFalse((self.base / "review" / "layouts" / f"{first['id']}.png").exists())

    def test_a_plus_request_defaults_to_thirteen_independent_jpg_jobs(self):
        path = p.init_project(self.base, "thirteen", marketplace="US", language="en", include_a_plus=True,
                              a_plus_canvas=[970, 600], a_plus_module="standard_image")
        m = p.read_json(path)
        self.assertEqual(len(m["jobs"]), 13)
        self.assertEqual(sum(j["kind"] == "a_plus" for j in m["jobs"]), 6)
        self.assertEqual(len({j["final_output"] for j in m["jobs"]}), 13)

    def test_compact_still_rejects_related_fact_change(self):
        m = self.ready()
        m["facts"] = [{"id": "known_fact", "text": "Known test fact", "evidence": "test fixture"}]
        m["jobs"][1]["claim_ids"] = ["known_fact"]
        finish_fixture(m, self.base)
        self.compact(m)
        m["facts"][0]["text"] = "Changed test fact"
        with self.assertRaises(p.PipelineError):
            p.delivery_check(m, self.base)

    def test_new_project_defaults_are_compact_without_inventing_copy(self):
        path = p.init_project(self.base, "new-compact", marketplace="US", language="en")
        m = p.read_json(path)
        self.assertEqual(m["review_dependency_version"], 2)
        self.assertEqual(m["style_contract"]["version"], 3)
        self.assertEqual(m["style_contract"]["selection"], "design_first")
        self.assertNotIn("copy_budget", m)
        self.assertTrue(all(j["final_output"].endswith(".jpg") for j in m["jobs"]))
        self.assertTrue(all(j["export"]["quality"] == 92 for j in m["jobs"]))

    def test_cli_removes_gallery_and_html_delivery_options(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                p.parser().parse_args(["gallery"])
            with self.assertRaises(SystemExit):
                p.parser().parse_args(["deliver", "--manifest", str(self.manifest), "--html"])

    def test_json_cli_is_one_document_for_staged_success_and_error(self):
        m = self.ready()
        command = [sys.executable, str(p.SCRIPT_DIR / "lc_image_pipeline.py")]
        for verb in ("prepare", "plan"):
            good = subprocess.run(command + [verb, "--manifest", str(self.manifest), "--json"], text=True, capture_output=True)
            self.assertEqual(good.returncode, 0, good.stderr)
            self.assertEqual(json.loads(good.stdout)["manifest"], str(self.manifest))
            self.assertTrue(json.loads(good.stdout)["ok"])
        bad = subprocess.run(command + ["--json", "prepare", "--manifest", str(self.manifest), "--jobs", "unknown"], text=True, capture_output=True)
        self.assertEqual(bad.returncode, 2)
        self.assertFalse(json.loads(bad.stdout)["ok"])

    def test_json_cli_cas_failure_never_prints_provisional_success(self):
        self.ready()
        output = io.StringIO()
        args = ["lc_image_pipeline.py", "prepare", "--manifest", str(self.manifest), "--json"]
        with patch.object(sys, "argv", args), patch("lc_transactions._merge", side_effect=ValueError("Fixture CAS conflict")), contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            code = p.main()
        self.assertEqual(code, 2)
        result = json.loads(output.getvalue())
        self.assertFalse(result["ok"])
        self.assertIn("CAS conflict", result["error"])

    def test_recompiling_a_quality_repair_does_not_reset_history(self):
        m = create_v3_fixture(self.base)
        prepare_fixture(m, self.base)
        j = m["jobs"][1]
        j["status"] = "generation_repair_needed"
        j["composition"] += "; repair the actual structure"
        bind_source_reviews(m, self.base)
        p.prepare(m, self.base)
        self.assertEqual(j["pending_attempt_kind"], "quality_repair")
        p.transition_job(m, SECONDARY_ID, "generating", None, self.base)
        self.assertEqual(j["generation_attempts"][-1]["kind"], "quality_repair")
        j["status"] = "generation_repair_needed"
        j["composition"] += "; another repair"
        bind_source_reviews(m, self.base)
        p.prepare(m, self.base)
        self.assertEqual(j["quality_repairs"], 1)
        p.transition_job(m, SECONDARY_ID, "generating", None, self.base)
        self.assertEqual(j["status"], "blocked")

    def test_dispatch_snapshots_geometry_without_rebinding_prompt(self):
        m = create_v3_fixture(self.base)
        m["review_dependency_version"] = 2
        prepare_fixture(m, self.base)
        j = m["jobs"][1]
        before = j["prompt_hash"]
        geometry = p.generation_geometry(j)
        p.transition_job(m, SECONDARY_ID, "generating", None, self.base)
        self.assertEqual(j["generation_geometry_lock"], geometry)
        self.assertEqual(j["generation_attempts"][-1]["geometry"], geometry)
        self.assertEqual(p.generation_fingerprint(m, j, self.base), before)

    def test_copy_edit_after_preflight_cannot_spend_a_model_attempt(self):
        m = create_v3_fixture(self.base)
        m["style_contract"] = {**p.default_style_contract(), "color_roles": {"headline": "#E8D5B0", "body": "#E8D5B0"}}
        m["copy_budget"] = p.default_copy_budget()
        m["facts"] = [{"id": "fixture_fact", "text": "Known test view", "evidence": "Synthetic test fixture"}]
        j = m["jobs"][1]
        j.update(text_mode="local_overlay", placement_mode="manual", claim_ids=["fixture_fact"],
                 target_product_bbox_norm=[.25, .34, .56, .56],
                 layout={"version": 3, "recipe": "photo_overlay", "text_groups": [
                     {"id": "title", "headline": "Fixture View", "box": [.08, .06, .84, .2], "evidence_refs": ["fixture_fact"]}]})
        prepare_fixture(m, self.base)
        self.assertEqual(m["generation_gate"]["status"], "open", m["generation_gate"])
        self.assertTrue(j["typography_dispatch_binding"]["passed"])
        before = p.generation_fingerprint(m, j, self.base)
        j["layout"]["text_groups"][0]["headline"] = "W" * 100
        self.assertEqual(p.generation_fingerprint(m, j, self.base), before)
        self.assertTrue(p.project_contract_report(m)["passed"])
        with self.assertRaisesRegex(p.PipelineError, "Typography preflight.*stale"):
            p.transition_job(m, SECONDARY_ID, "generating", None, self.base)
        self.assertEqual(j.get("generation_attempts", []), [])


if __name__ == "__main__":
    unittest.main()
