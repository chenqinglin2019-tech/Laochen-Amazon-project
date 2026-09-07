"""No-model scheduling and dispatch-evidence regressions on marked fixtures."""
from __future__ import annotations

import copy
import io
import json
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import lc_image_pipeline as p
import lc_scheduler as s
import lc_workflow as w
from pipeline_test_support import (MAIN_ID, SECONDARY_ID, NOTE, create_v3_fixture,
                                   prepare_fixture)


def manifest():
    return {"scheduler_policy": s.default_policy(), "concurrency": 2,
            "generation_gate": {"status": "open"}, "anchor_job_id": "anchor",
            "jobs": [{"id": "anchor", "status": "qa_passed", "render_mode": "reference_generate"},
                     {"id": "next", "status": "pending", "render_mode": "reference_generate"}]}


def attempt(m, identifier="a", kind="initial"):
    value = {"id": identifier, "kind": kind, "dispatched_at": 100.0}
    s.bind_attempt(m, value)
    return value


class SchedulerTests(unittest.TestCase):
    def test_initial_successes_grow_only_the_current_tier(self):
        m = manifest()
        a, b, late = (attempt(m, name) for name in ("a", "b", "late"))
        s.record_success(m, a, now=101)
        self.assertEqual(m["concurrency"], 2)
        s.record_success(m, b, now=102)
        self.assertEqual(m["concurrency"], 3)
        s.record_success(m, b, now=102)
        s.record_success(m, late, now=103)
        self.assertEqual(m["network_health"]["adaptive_successes"], 0)
        s.record_success(m, attempt(m, "c"), now=104)
        s.record_success(m, attempt(m, "d"), now=105)
        self.assertEqual(m["concurrency"], 4)
        for i in range(4):
            s.record_success(m, attempt(m, str(i)), now=106+i)
        self.assertEqual(m["concurrency"], 4)

    def test_each_retry_or_quality_repair_attempt_counts_only_its_first_success(self):
        m = manifest()
        repair = attempt(m, "repair", "quality_repair")
        retry = attempt(m, "retry", "transient_retry")
        s.record_success(m, repair, now=120)
        s.record_success(m, repair, now=121)
        self.assertEqual(m["concurrency"], 2)
        self.assertEqual(m["network_health"]["adaptive_successes"], 1)
        s.record_success(m, retry, now=122)
        self.assertEqual(m["concurrency"], 3)

    def test_anchor_success_does_not_skip_qa_gate(self):
        m = manifest()
        m["jobs"][0]["status"] = "generated"
        with self.assertRaisesRegex(ValueError, "ANCHOR_REQUIRED"):
            s.require_capacity(m, m["jobs"][1])
        s.record_success(m, attempt(m), now=120)
        self.assertEqual(m["concurrency"], 2)
        self.assertNotIn("adaptive_successes", m["network_health"])

    def test_tool_capacity_is_a_shared_ceiling_and_does_not_force_growth(self):
        m = manifest()
        s.set_tool_capacity(m, 1)
        self.assertEqual(s.state(m)["model_capacity"], 1)
        s.record_success(m, attempt(m), now=101)
        s.record_success(m, attempt(m, "b"), now=102)
        self.assertEqual(m["concurrency"], 2)
        m["jobs"][1]["status"] = "generating"
        with self.assertRaisesRegex(ValueError, "concurrency is full"):
            s.require_capacity(m, {"id": "extra"})

    def test_product_and_title_effects_share_slots(self):
        m = manifest()
        m["jobs"][0]["title_effect_attempts"] = [{"status": "started"}]
        m["jobs"][1]["status"] = "generating"
        self.assertEqual(s.state(m)["model_capacity"], 0)
        m["jobs"][0]["title_effect_attempts"][0]["status"] = "returned"
        self.assertEqual(s.state(m)["model_capacity"], 1)

    def test_rate_limit_late_success_and_retry_after(self):
        m = manifest()
        a, late = attempt(m), attempt(m, "late")
        s.record_failure(m, a, "HTTP 429", retry_after_seconds=120, now=200)
        self.assertEqual(m["concurrency"], 1)
        self.assertEqual(s.state(m, now=250)["model_capacity"], 0)
        self.assertEqual(s.state(m, now=250)["retry_after_seconds"], 70)
        self.assertEqual(s.state(m, now=321)["model_capacity"], 1)
        before = copy.deepcopy(m)
        s.record_failure(m, a, "HTTP 429", retry_after_seconds=120, now=250)
        self.assertEqual(m, before)
        s.record_success(m, late, now=322)
        self.assertEqual(m["network_health"]["adaptive_successes"], 0)
        s.record_success(m, attempt(m, "new1"), now=323)
        s.record_success(m, attempt(m, "new2"), now=324)
        self.assertEqual(m["concurrency"], 2)

    def test_timeout_backoff_and_cooldown_preserve_inflight_calls(self):
        m = manifest()
        m["concurrency"] = 4
        m["jobs"].extend({"id": f"run{i}", "status": "generating"} for i in range(4))
        s.record_failure(m, attempt(m), "timeout", now=200)
        self.assertEqual(m["concurrency"], 3)
        self.assertEqual(s.state(m, now=201)["model_capacity"], 0)
        self.assertEqual(s.active_count(m), 4)
        s.record_failure(m, attempt(m, "second"), "timed out", now=210)
        self.assertEqual(m["concurrency"], 1)
        s.record_success(m, attempt(m, "early"), now=211)
        self.assertEqual(m["network_health"]["adaptive_successes"], 0)
        s.record_success(m, attempt(m, "fresh1"), now=271)
        s.record_success(m, attempt(m, "fresh2"), now=272)
        self.assertEqual(m["concurrency"], 2)

    def test_quality_failure_does_not_trigger_network_backoff(self):
        m = manifest()
        s.record_failure(m, attempt(m), "product detail QA failed", now=200)
        self.assertEqual(m["concurrency"], 2)
        self.assertNotIn("cooldown_until", m["network_health"])

    def test_explicit_wait_on_other_failure_invalidates_older_successes(self):
        m = manifest()
        failed, late = attempt(m), attempt(m, "late")
        s.record_failure(m, failed, "provider temporarily unavailable", retry_after_seconds=5, now=200)
        self.assertEqual(m["concurrency"], 2)
        self.assertEqual(m["network_health"]["scheduler_epoch"], 1)
        self.assertEqual(m["network_health"]["last_backoff_at"], 200)
        self.assertEqual(m["network_health"]["cooldown_until"], 260)
        self.assertEqual(s.state(m, now=202)["model_capacity"], 0)
        self.assertEqual(s.state(m, now=206)["model_capacity"], 2)
        s.record_success(m, attempt(m, "during_cooldown"), now=206)
        s.record_success(m, late, now=261)
        self.assertEqual(m["network_health"]["adaptive_successes"], 0)
        s.record_success(m, attempt(m, "fresh1"), now=262)
        s.record_success(m, attempt(m, "fresh2"), now=263)
        self.assertEqual(m["concurrency"], 3)

    def test_other_failure_breaks_only_adaptive_timeout_streak(self):
        m = manifest()
        m["concurrency"] = 4
        s.record_failure(m, attempt(m), "timeout", now=200)
        self.assertEqual(m["concurrency"], 3)
        s.record_failure(m, attempt(m, "other"), "transport disconnected", now=201)
        self.assertEqual(m["network_health"]["consecutive_timeouts"], 0)
        s.record_failure(m, attempt(m, "timeout2"), "timeout", now=202)
        self.assertEqual(m["concurrency"], 2)
        old = manifest()
        old.pop("scheduler_policy")
        s.record_failure(old, {}, "timeout", now=200)
        s.record_failure(old, {}, "transport disconnected", now=201)
        s.record_failure(old, {}, "timeout", now=202)
        self.assertEqual(old["concurrency"], 1)

    def test_legacy_limit_and_backoff_are_preserved(self):
        m = manifest()
        m.pop("scheduler_policy")
        self.assertEqual(s.validate(m), [])
        m["concurrency"] = 3
        self.assertTrue(s.validate(m))
        m["concurrency"] = 2
        s.record_failure(m, {}, "timeout")
        self.assertEqual(m["concurrency"], 2)
        s.record_failure(m, {}, "timeout")
        self.assertEqual(m["concurrency"], 1)
        s.record_success(m, {})
        self.assertEqual(m["concurrency"], 1)

    def test_invalid_controls_fail_closed(self):
        for bad in (True, -1, 0, 5, float("nan"), None):
            m = manifest()
            m["network_health"] = {"tool_capacity": bad}
            self.assertTrue(s.validate(m))
            with self.assertRaises(ValueError):
                s.set_tool_capacity(manifest(), bad)
        for bad in (True, -1, float("inf"), float("nan"), 10**400):
            with self.assertRaises(ValueError):
                s.retry_after(bad)
        m = manifest()
        m["scheduler_policy"] = None
        self.assertTrue(s.validate(m))

    def test_model_capacity_does_not_hide_ready_local_work(self):
        m = manifest()
        m["jobs"].extend({"id": f"run{i}", "status": "generating", "render_mode": "reference_generate"}
                         for i in range(2))
        m["jobs"].append({"id": "local", "status": "pending", "render_mode": "pixel_composite"})
        plan = p.execution_plan(m)
        self.assertEqual([(j["id"], j["action"]) for j in plan["dispatch"]], [("local", "compose")])
        m["network_health"] = {"retry_after_until": time.time()+100}
        self.assertEqual(p.execution_plan(m)["dispatch"][0]["id"], "local")


class DispatchIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lc-scheduler-fixture-")
        self.base = Path(self.temp.name).resolve()
        self.m = create_v3_fixture(self.base)
        prepare_fixture(self.m, self.base)

    def tearDown(self):
        self.temp.cleanup()

    def secondary(self):
        return p.find_by_id(self.m["jobs"], SECONDARY_ID)

    def test_dispatch_reads_bound_evidence_without_creating_previews(self):
        before = {str(path): path.stat().st_mtime_ns for path in self.base.rglob("*") if path.is_file()}
        with patch("lc_quality.assess_sources", side_effect=AssertionError("no assessment materialization")), \
                patch.object(Image, "open", side_effect=AssertionError("no raster decode")):
            p.transition_job(self.m, SECONDARY_ID, "generating", NOTE, self.base)
        after = {str(path): path.stat().st_mtime_ns for path in self.base.rglob("*") if path.is_file()}
        self.assertEqual(before, after)

    def test_dispatch_rejects_changed_bytes_region_review_or_prepared_metrics(self):
        changes = [lambda m: m["references"][0]["quality_review"].update(clarity="unknown"),
                   lambda m: m["references"][0].update(product_bbox_norm=[.1,.1,.7,.8]),
                   lambda m: m["references"][0].update(product_pixel_size=[9999,9999]),
                   lambda m: p.find_by_id(m["jobs"], SECONDARY_ID)["source_assessment"].update(reviewed_context_fingerprint="stale")]
        for change in changes:
            with self.subTest(change=change):
                m = copy.deepcopy(self.m)
                change(m)
                with self.assertRaisesRegex(p.PipelineError, "Current source evidence"):
                    p.transition_job(m, SECONDARY_ID, "generating", NOTE, self.base)
        Image.new("RGB", (1600,1600), "red").save(self.base / "source/product_front.png")
        with self.assertRaisesRegex(p.PipelineError, "Current source evidence"):
            p.transition_job(self.m, SECONDARY_ID, "generating", NOTE, self.base)

    def test_missing_source_metadata_requires_plan(self):
        (self.base / "review/source_quality/index.json").unlink()
        with self.assertRaisesRegex(p.PipelineError, "SOURCE_PREPARATION_STALE"):
            p.transition_job(self.m, SECONDARY_ID, "generating", NOTE, self.base)

    def test_recursive_real_evidence_is_rechecked(self):
        ref = self.m["references"][0]
        original = copy.deepcopy(ref)
        original.update(id="real_evidence", path="source/real-evidence.png")
        (self.base / original["path"]).write_bytes((self.base / ref["path"]).read_bytes())
        self.m["references"].append(original)
        ref["provenance"] = {"kind": "generated", "qa_verdict": "pass",
                             "source_reference_ids": [original["id"]],
                             "reviewed_source_hashes": {original["id"]: original["sha256"]}}
        # Only the model job is needed here; the real-pixel job cannot pretend
        # that a generated master retains its original source identity.
        self.m["jobs"] = [self.secondary()]
        for detail in self.m["critical_details"]:
            detail["visibility"].pop(MAIN_ID, None)
        prepare_fixture(self.m, self.base)
        result = s.source_dispatch_decision(self.m, self.secondary(), self.base)
        self.assertEqual(result["blocked_reasons"], [])
        Image.new("RGB", (1600,1600), "blue").save(self.base / original["path"])
        result = s.source_dispatch_decision(self.m, self.secondary(), self.base)
        self.assertTrue(any("real_evidence" in value for value in result["blocked_reasons"]))

    def test_corrupt_prepared_index_fails_closed(self):
        p.write_json(self.base / "review/source_quality/index.json", [])
        result = s.source_dispatch_decision(self.m, self.secondary(), self.base)
        self.assertTrue(any("SOURCE_PREPARATION_STALE" in value for value in result["blocked_reasons"]))

    def test_layer_mask_content_is_verified_without_decode(self):
        main = p.find_by_id(self.m["jobs"], MAIN_ID)
        Image.new("L", (1600,1600), 0).save(self.base / "source/product_mask.png")
        result = s.source_dispatch_decision(self.m, main, self.base)
        self.assertTrue(any("SOURCE_LAYER_ASSET_STALE" in value for value in result["blocked_reasons"]))

    def test_combined_return_and_ingest_is_exact_and_idempotent(self):
        p.transition_job(self.m, SECONDARY_ID, "generating", NOTE, self.base)
        identifier = self.secondary()["active_attempt_id"]
        w.attempt_event(self.m, SECONDARY_ID, identifier, "tool_started")
        artifact = self.base / "synthetic-output.png"
        Image.new("RGB", (1600,1600), "white").save(artifact)
        returned = time.time()
        result = w.ingest(self.m, self.base, SECONDARY_ID, artifact, identifier, tool_returned_at=returned)
        self.assertFalse(result["idempotent"])
        history = self.secondary()["generation_attempts"][-1]
        self.assertEqual(history["tool_returned_at"], returned)
        self.assertIn("handoff", {value["stage"] for value in self.secondary()["timings"]})
        before = copy.deepcopy(self.m)
        self.assertTrue(w.ingest(self.m, self.base, SECONDARY_ID, artifact, identifier,
                                 tool_returned_at=returned)["idempotent"])
        self.assertEqual(self.m, before)
        with self.assertRaisesRegex(p.PipelineError, "cannot be rewritten"):
            w.ingest(self.m, self.base, SECONDARY_ID, artifact, identifier, tool_returned_at=returned-.01)

    def test_invalid_combined_return_never_admits_artifact(self):
        p.transition_job(self.m, SECONDARY_ID, "generating", NOTE, self.base)
        identifier = self.secondary()["active_attempt_id"]
        artifact = self.base / "synthetic-output.png"
        Image.new("RGB", (1600,1600), "white").save(artifact)
        before = copy.deepcopy(self.m)
        with self.assertRaisesRegex(p.PipelineError, "prior tool_started"):
            w.ingest(self.m, self.base, SECONDARY_ID, artifact, identifier, tool_returned_at=time.time())
        self.assertEqual(self.m, before)
        self.assertFalse((self.base / self.secondary()["raw_output"]).exists())

    def test_new_scheduler_policy_does_not_change_generation_fingerprint(self):
        before = p.generation_fingerprint(self.m, self.secondary(), self.base)
        self.m.update(scheduler_policy=s.default_policy(), concurrency=4,
                      network_health={"tool_capacity": 2, "scheduler_epoch": 2, "cooldown_until": 100})
        self.assertEqual(p.generation_fingerprint(self.m, self.secondary(), self.base), before)

    def test_pending_retry_propagates_explicit_wait_and_preserves_attempt_budget(self):
        self.m["scheduler_policy"] = s.default_policy()
        p.transition_job(self.m, SECONDARY_ID, "generating", NOTE, self.base)
        identifier = self.secondary()["active_attempt_id"]
        p.transition_job(self.m, SECONDARY_ID, "pending", "429", self.base, retry_after_seconds=120)
        self.assertEqual(self.m["concurrency"], 1)
        self.assertEqual(self.secondary()["generation_attempts"][-1]["scheduler_outcome"], "failed")
        self.assertEqual(self.secondary()["attempts"], 1)
        with self.assertRaisesRegex(p.PipelineError, "MODEL_RETRY_AFTER"):
            p.transition_job(self.m, SECONDARY_ID, "generating", NOTE, self.base)
        self.assertEqual(self.secondary()["active_attempt_id"], identifier)

    def test_cli_controls_parse_and_new_projects_opt_in(self):
        args = p.parser().parse_args(["plan", "--manifest", "manifest.json", "--tool-capacity", "1"])
        self.assertEqual(args.tool_capacity, 1)
        args = p.parser().parse_args(["ingest", "--manifest", "manifest.json", "--job", "job", "--artifact",
                                     "output.png", "--attempt-id", "a", "--tool-returned-at", "100"])
        self.assertEqual(args.tool_returned_at, 100)
        path = p.init_project(self.base / "new", "scheduler-fixture", marketplace="US", language="en")
        created = p.read_json(path)
        self.assertEqual(created["scheduler_policy"], s.default_policy())
        self.assertEqual(created["concurrency"], 2)

    def assert_dispatch_paths(self, result):
        self.assertTrue(result["dispatch"])
        for entry in result["dispatch"]:
            job = p.find_by_id(self.m["jobs"], entry["id"])
            self.assertEqual(entry["prompt_file"], job["prompt_file"])
            self.assertEqual(entry["generation_reference_paths"], job["generation_reference_paths"])
            self.assertEqual(entry["prompt_hash"], job["prompt_hash"])
            self.assertFalse(Path(entry["prompt_file"]).is_absolute())
            self.assertTrue((self.base / entry["prompt_file"]).is_file())
            for value in entry["generation_reference_paths"]:
                self.assertTrue(p.resolve_path(value, self.base).is_file())
                self.assertNotIn(".lc-transactions", value)

    def prepared_queue(self):
        from pipeline_test_support import fixture_job, simulate_secondary_output, finish_fixture
        for job in self.m["jobs"]:
            job["generation_dependency_version"] = 2
        prepare_fixture(self.m, self.base)
        simulate_secondary_output(self.m, self.base)
        finish_fixture(self.m, self.base)
        for identifier in ("03_next", "04_next"):
            job = fixture_job(identifier, "listing", "reference_generate")
            job["generation_dependency_version"] = 2
            self.m["jobs"].append(job)
            for detail in self.m["critical_details"]:
                detail["visibility"][identifier] = "required"
        prepare_fixture(self.m, self.base)
        self.assertTrue(s.anchor_passed(self.m))

    def test_staged_plan_returns_canonical_prepared_paths_after_merge(self):
        import lc_transactions as tx
        manifest_path = self.base / "project_manifest.json"
        p.write_json(manifest_path, self.m)
        output = io.StringIO()
        def operation(staged):
            return p.run_command(p.parser().parse_args(["plan", "--manifest", str(staged), "--json"]))
        with redirect_stdout(output):
            tx.run_staged_command(manifest_path, None, operation, command_name="plan")
        result = json.loads(output.getvalue())
        self.m = p.read_json(manifest_path)
        self.assert_dispatch_paths(result)
        self.assertNotIn(".lc-transactions", json.dumps(result["dispatch"]))

    def test_ingest_returns_next_prepared_paths_immediately(self):
        self.prepared_queue()
        job = p.find_by_id(self.m["jobs"], "03_next")
        p.transition_job(self.m, job["id"], "generating", NOTE, self.base)
        identifier = job["active_attempt_id"]
        w.attempt_event(self.m, job["id"], identifier, "tool_started")
        artifact = self.base / "synthetic-return.png"
        Image.new("RGB", tuple(job["canvas"]), "white").save(artifact)
        result = w.ingest(self.m, self.base, job["id"], artifact, identifier, tool_returned_at=time.time())
        self.assertEqual([value["id"] for value in result["dispatch"]], ["04_next"])
        self.assert_dispatch_paths(result)

    def test_review_submit_returns_next_prepared_paths_immediately(self):
        from pipeline_test_support import simulate_secondary_output
        self.prepared_queue()
        job = p.find_by_id(self.m["jobs"], "03_next")
        simulate_secondary_output(self.m, self.base, job_id=job["id"])
        result = w.review_prepare(self.m, self.base, job["id"],
                                  {"raw_product_bbox_norm": job["target_product_bbox_norm"],
                                   "detail_output_bbox_norms": job["fixture_output_detail_boxes"]})
        packet = p.read_json(Path(result["packet"]))
        self.assertTrue(self.m["test_fixture"])
        for field in ("semantic_qa_results", "policy_qa_results", "detail_qa_results"):
            for key in packet["reviews"][field]:
                packet["reviews"][field][key] = {"verdict": "pass", "notes": NOTE}
        packet["reviews"]["ai_disclosure"] = {"human_source": "none", "notes": NOTE}
        submitted = w.review_submit(self.m, self.base, packet)
        self.assertEqual(submitted["status"], "qa_passed")
        self.assertEqual([value["id"] for value in submitted["dispatch"]], ["04_next"])
        self.assert_dispatch_paths(submitted)


class TitleSchedulerIntegrationTests(unittest.TestCase):
    def setUp(self):
        import test_lc_title_effects as fixtures
        self.fixture = fixtures.TitleEffectTests()
        self.fixture.setUp()
        self.m, self.job, self.base = self.fixture.manifest, self.fixture.job, self.fixture.base
        self.m.update(scheduler_policy=s.default_policy(), concurrency=2,
                      generation_gate={"status": "open"}, anchor_job_id="anchor",
                      jobs=[{"id": "anchor", "status": "qa_passed"}, self.job])

    def tearDown(self):
        self.fixture.tearDown()
        self.fixture.doCleanups()

    def test_actual_title_start_uses_the_tool_and_anchor_gates(self):
        import lc_title_effects as effects
        self.fixture.prepare()
        s.set_tool_capacity(self.m, 1)
        self.m["jobs"].append({"id": "busy", "status": "generating"})
        with self.assertRaisesRegex(effects.TitleEffectError, "CONCURRENCY_FULL"):
            effects.attempt_event(self.m, self.base, self.job, "tool_started")
        self.m["jobs"].pop()
        self.m["jobs"][0]["status"] = "generated"
        with self.assertRaisesRegex(effects.TitleEffectError, "ANCHOR_REQUIRED"):
            effects.attempt_event(self.m, self.base, self.job, "tool_started")

    def test_title_failure_backoff_is_shared_and_idempotent(self):
        import lc_title_effects as effects
        self.fixture.prepare()
        started = effects.attempt_event(self.m, self.base, self.job, "tool_started", at=100)
        effects.attempt_event(self.m, self.base, self.job, "failed", attempt_id=started["id"],
                              at=101, reason="429", retry_after_seconds=30)
        self.assertEqual(self.m["concurrency"], 1)
        self.assertEqual(s.state(self.m)["model_capacity"], 0)
        before = copy.deepcopy(self.m)
        effects.attempt_event(self.m, self.base, self.job, "failed", attempt_id=started["id"],
                              at=101, reason="429", retry_after_seconds=30)
        self.assertEqual(self.m, before)

    def test_real_title_ingest_counts_once_towards_shared_growth(self):
        self.fixture.ingest()
        self.assertEqual(self.m["network_health"]["adaptive_successes"], 1)
        before = copy.deepcopy(self.m)
        import lc_title_effects as effects
        effects.ingest(self.m, self.base, self.job, self.base / "candidate.png", self.base / "mask.png",
                       attempt_id=self.job["title_effect_attempts"][-1]["id"])
        self.assertEqual(self.m, before)
        s.record_success(self.m, attempt(self.m, "product"))
        self.assertEqual(self.m["concurrency"], 3)


if __name__ == "__main__":
    unittest.main()
