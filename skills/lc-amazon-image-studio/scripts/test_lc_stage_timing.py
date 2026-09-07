"""Stage timing uses synthetic fixtures and never invokes a model."""
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
import lc_image_pipeline as p
import lc_workflow as w
from lc_stage_timing import record_batch_stage, record_stage
from pipeline_test_support import (MAIN_ID, SECONDARY_ID, NOTE, create_v3_fixture,
                                   prepare_fixture, ready_fixture, simulate_secondary_output)


class StageTimingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lc-stage-timing-")
        self.base = Path(self.temp.name)
        self.m = create_v3_fixture(self.base)

    def tearDown(self):
        self.temp.cleanup()

    @property
    def job(self):
        return self.m["jobs"][1]

    def test_batch_record_is_owned_once_and_never_a_business_dependency(self):
        self.m = ready_fixture(self.base)
        before = [(p.current_fingerprints(self.m, job, self.base), p.qa_fingerprint(self.m, job, self.base)) for job in self.m["jobs"]]
        record_batch_stage(self.m, [MAIN_ID, SECONDARY_ID], "planning", seconds=.2)
        record_stage(self.job, "reference_compile", seconds=.01)
        after = [(p.current_fingerprints(self.m, job, self.base), p.qa_fingerprint(self.m, job, self.base)) for job in self.m["jobs"]]
        self.assertEqual(before, after)
        records = [item for job in self.m["jobs"] for item in job["timings"] if item.get("scope") == "batch" and item["seconds"] == .2]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["jobs"], [MAIN_ID, SECONDARY_ID])

    def test_reference_compile_records_real_span_and_external_analysis_unavailable(self):
        self.job["text_mode"] = "local_overlay"
        self.job["design_reference_id"] = "missing-fixture-reference"
        p.prepare(self.m, self.base, [SECONDARY_ID])
        self.assertEqual(self.job["design_resolution"]["status"], "needs_input")
        record = next(item for item in self.job["timings"] if item["stage"] == "reference_compile")
        self.assertEqual(record["stage"], "reference_compile")
        self.assertGreaterEqual(record["seconds"], 0)
        self.assertIsNone(record["external_visual_analysis_seconds"])
        self.assertNotIn("timings", self.m["jobs"][0])

    def test_noop_prepare_records_planning_without_render_or_pixel_changes(self):
        self.m = ready_fixture(self.base)
        outputs = [self.base / job["final_output"] for job in self.m["jobs"]]
        before = [(path.stat().st_mtime_ns, p.sha256_file(path)) for path in outputs]
        hashes = [p.current_fingerprints(self.m, job, self.base) for job in self.m["jobs"]]
        with patch("lc_layout.render_batch", side_effect=AssertionError("No-op timing cannot launch rendering")):
            p.prepare(self.m, self.base)
            p.aspect_safe_postprocess(self.m, self.base)
        self.assertEqual(before, [(path.stat().st_mtime_ns, p.sha256_file(path)) for path in outputs])
        self.assertEqual(hashes, [p.current_fingerprints(self.m, job, self.base) for job in self.m["jobs"]])
        record = next(item for item in reversed(self.m["jobs"][0]["timings"]) if item["stage"] == "planning")
        self.assertIsNone(record["external_agent_planning_seconds"])
        self.assertEqual(record["includes"], ["reference_compile"])

    def test_review_wait_submit_and_prepare_are_separate_without_changing_legacy_span(self):
        prepare_fixture(self.m, self.base)
        simulate_secondary_output(self.m, self.base)
        result = w.review_prepare(self.m, self.base, SECONDARY_ID,
            {"raw_product_bbox_norm": self.job["target_product_bbox_norm"], "detail_output_bbox_norms": self.job["fixture_output_detail_boxes"]})
        path = Path(result["packet"])
        packet = p.read_json(path)
        before = (path.stat().st_mtime_ns, p.sha256_file(path), self.job["review_request"]["ready_at"])
        with patch("lc_layout.render_batch", side_effect=AssertionError("Cached review cannot render")):
            self.assertTrue(w.review_prepare(self.m, self.base, SECONDARY_ID)["cached"])
        self.assertEqual(before, (path.stat().st_mtime_ns, p.sha256_file(path), self.job["review_request"]["ready_at"]))
        self.assertTrue(self.job["timings"][-1]["cached"])
        for field in ("semantic_qa_results", "policy_qa_results", "detail_qa_results"):
            for key in packet["reviews"][field]:
                packet["reviews"][field][key] = {"verdict": "pass", "notes": NOTE}
        packet["reviews"]["ai_disclosure"] = {"human_source": "none", "notes": NOTE}
        self.assertEqual(w.review_submit(self.m, self.base, packet)["status"], "qa_passed")
        records = {item["stage"]: item for item in self.job["timings"]}
        self.assertEqual(records["review"]["measurement"], "review_prepared_to_submitted")
        self.assertEqual(records["review_wait"]["measurement"], "packet_ready_to_submit_start")
        self.assertEqual(records["review_submit"]["includes"], ["export", "qa"])
        self.assertLessEqual(records["review_wait"]["seconds"], records["review"]["seconds"] + .001)
        self.assertIsNone(records["review_wait"]["human_active_review_seconds"])
        count = sum(item["stage"] == "review_wait" for item in self.job["timings"])
        self.assertTrue(w.review_submit(self.m, self.base, packet)["idempotent"])
        self.assertEqual(count, sum(item["stage"] == "review_wait" for item in self.job["timings"]))
        self.assertTrue(self.job["timings"][-1]["cached"])

    def test_cli_transition_and_ingest_record_actual_lock_wait(self):
        prepare_fixture(self.m, self.base)
        manifest = self.base / "project_manifest.json"
        p.write_json(manifest, self.m)
        executable = ("import sys;sys.path.insert(0,sys.argv.pop(1));import lc_image_pipeline as p;"
                      "print('ready',flush=True);raise SystemExit(p.main())")
        with w.manifest_lock(manifest):
            process = subprocess.Popen([sys.executable, "-c", executable, str(Path(p.__file__).parent), "transition",
                "--manifest", str(manifest), "--job", SECONDARY_ID, "--status", "generating", "--reason", NOTE],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.assertEqual(process.stdout.readline().strip(), "ready")
            time.sleep(.12)
        stdout, stderr = process.communicate(timeout=20)
        self.assertEqual(process.returncode, 0, stdout + stderr)
        self.m = p.read_json(manifest)
        event = next(item for item in self.job["timings"] if item["stage"] == "lock_wait")
        self.assertGreater(event["seconds"], .06)
        self.assertEqual(event["command"], "transition")
        artifact = self.base / "fixture-artifact.png"
        Image.new("RGB", (1600, 1600), "white").save(artifact)
        result = subprocess.run([sys.executable, str(Path(p.__file__)), "ingest", "--manifest", str(manifest),
            "--job", SECONDARY_ID, "--artifact", str(artifact), "--attempt-id", self.job["active_attempt_id"]],
            capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.m = p.read_json(manifest)
        self.assertEqual(self.job["status"], "generated")
        self.assertEqual([item["command"] for item in self.job["timings"] if item["stage"] == "lock_wait"], ["transition", "ingest"])


if __name__ == "__main__":
    unittest.main()
