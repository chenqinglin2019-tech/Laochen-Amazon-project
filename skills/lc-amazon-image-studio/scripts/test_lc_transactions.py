"""Transaction regression fixtures; no image model or production files involved."""
from __future__ import annotations

import copy
import json
import multiprocessing
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import lc_image_pipeline as p
import lc_transactions as tx
from lc_workflow import manifest_lock


def _worker(path, job_id, ready, release, results, *, fail=False, crash=False, report=False, no_state=False):
    path = Path(path).resolve()

    def operation(staged):
        manifest = p.read_json(staged)
        job = p.find_by_id(manifest["jobs"], job_id)
        output = staged.parent / "final" / f"{job_id}.png"
        output.parent.mkdir(exist_ok=True)
        output.write_bytes(("new-" + job_id).encode())
        if no_state:
            second = staged.parent / "review/layouts" / f"{job_id}.png"
            second.parent.mkdir(parents=True, exist_ok=True)
            second.write_bytes(b"second artifact")
        else:
            job.update(status="qa_passed", layout_result={"output_path": str(output)})
        if report:
            p.write_json(staged.parent / "qa_report.json", {"jobs": [
                {"id": value["id"], "status": value["status"]} for value in manifest["jobs"]]})
        p.write_json(staged, manifest)
        ready.set()
        if not release.wait(15):
            raise RuntimeError("test release timed out")
        return 2 if fail else 0

    original = tx.os.replace

    def replace(source, destination):
        original(source, destination)
        if crash and Path(destination) == path.parent / "final" / f"{job_id}.png":
            os._exit(21)

    try:
        with patch.object(tx.os, "replace", side_effect=replace):
            value = tx.run_staged_command(path, [job_id], operation, command_name="postprocess")
        results.put(("ok", value))
    except BaseException as exc:
        results.put((type(exc).__name__, str(exc)))


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lc-transaction-test-")
        self.base = Path(self.temp.name).resolve()
        self.path = self.base / "project_manifest.json"
        self.manifest = {"test_fixture": True, "project_id": "fixture", "concurrency": 2,
                         "generation_gate": {"status": "open"},
                         "facts": [{"id": "style", "text": "known fixture"}],
                         "jobs": [{"id": key, "status": "generated", "render_mode": "reference_generate",
                                   "raw_output": f"raw/{key}.png", "final_output": f"final/{key}.png"}
                                  for key in ("a", "b")]}
        p.write_json(self.path, self.manifest)
        for folder in ("raw", "final"):
            (self.base / folder).mkdir()
            for key in ("a", "b"):
                (self.base / folder / f"{key}.png").write_bytes(("old-" + key).encode())
        self.context = multiprocessing.get_context("spawn")
        self.processes = []

    def tearDown(self):
        for process in self.processes:
            if process.is_alive():
                process.terminate()
            process.join(10)
        self.temp.cleanup()

    def start(self, job_id="a", **kwargs):
        ready, release, results = self.context.Event(), self.context.Event(), self.context.Queue()
        process = self.context.Process(target=_worker, args=(str(self.path), job_id, ready, release, results), kwargs=kwargs)
        process.start()
        self.processes.append(process)
        self.assertTrue(ready.wait(10), "worker must reach lock-free heavy stage")
        return process, release, results

    def finish(self, process, release, results):
        release.set()
        outcome = results.get(timeout=15)
        process.join(10)
        self.assertEqual(process.exitcode, 0)
        return outcome

    def test_heavy_stage_does_not_hold_lock_or_publish_pixels(self):
        process, release, results = self.start()
        self.assertEqual((self.base / "final/a.png").read_bytes(), b"old-a")
        started = time.monotonic()
        with manifest_lock(self.path, timeout=.5):
            fresh = p.read_json(self.path)
            fresh["jobs"][1]["status"] = "review_pending"
            fresh["network_health"] = {"consecutive_timeouts": 0}
            p.write_json(self.path, fresh)
        self.assertLess(time.monotonic() - started, .5)
        self.assertEqual(self.finish(process, release, results), ("ok", 0))
        actual = p.read_json(self.path)
        self.assertEqual(actual["jobs"][0]["status"], "qa_passed")
        self.assertEqual(actual["jobs"][1]["status"], "review_pending")
        self.assertEqual(actual["jobs"][0]["layout_result"]["output_path"], str(self.base / "final/a.png"))

    def test_different_jobs_and_qa_reports_merge(self):
        first = self.start("a", report=True)
        second = self.start("b", report=True)
        self.assertEqual(self.finish(*second), ("ok", 0))
        self.assertEqual(self.finish(*first), ("ok", 0))
        actual = p.read_json(self.path)
        self.assertEqual([job["status"] for job in actual["jobs"]], ["qa_passed", "qa_passed"])
        report = p.read_json(self.base / "qa_report.json")
        self.assertEqual(report["summary"]["passed"], 2)

    def test_forked_report_uses_current_metadata_and_exact_whole_report_digest(self):
        current = {"schema_version": 2, "project_id": "old-project", "jobs": [
            {"id": "a", "status": "qa_passed"}, {"id": "b", "status": "review_pending"}]}
        proposed = {"schema_version": 3, "project_id": "new-project", "jobs": [
            {"id": "a", "status": "qa_passed"}, {"id": "b", "status": "qa_passed"}],
            "summary": {"passed": 2, "repair_needed": 0, "blocked": 0, "failed": 0, "review_pending": 0}}
        full = tx._merge_qa(current, proposed, {"a", "b"})
        self.assertEqual(p.digest(full), p.digest(proposed))
        partial = tx._merge_qa(current, proposed, {"a"})
        self.assertEqual(partial["project_id"], "new-project")
        self.assertEqual(partial["schema_version"], 3)
        self.assertEqual(partial["jobs"][1], current["jobs"][1])
        self.assertEqual(partial["summary"]["review_pending"], 1)

    def test_same_job_conflict_rejects_without_overwrite(self):
        first, second = self.start("a"), self.start("a")
        self.assertEqual(self.finish(*first), ("ok", 0))
        before = self.path.read_bytes()
        image_stat = (self.base / "final/a.png").stat().st_mtime_ns
        outcome = self.finish(*second)
        self.assertEqual(outcome[0], "TransactionConflict")
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(image_stat, (self.base / "final/a.png").stat().st_mtime_ns)

    def test_shared_evidence_change_rejects(self):
        worker = self.start()
        with manifest_lock(self.path):
            fresh = p.read_json(self.path)
            fresh["facts"][0]["text"] = "different verified fact"
            p.write_json(self.path, fresh)
        self.assertEqual(self.finish(*worker)[0], "TransactionConflict")
        self.assertEqual((self.base / "final/a.png").read_bytes(), b"old-a")

    def test_raw_content_change_rejects(self):
        worker = self.start()
        (self.base / "raw/a.png").write_bytes(b"different raw image")
        self.assertEqual(self.finish(*worker)[0], "TransactionConflict")
        self.assertEqual((self.base / "final/a.png").read_bytes(), b"old-a")

    def test_interrupted_commit_rolls_back_before_next_writer(self):
        process, release, results = self.start(crash=True)
        release.set()
        process.join(15)
        self.assertEqual(process.exitcode, 21)
        self.assertEqual((self.base / "final/a.png").read_bytes(), b"new-a")
        with manifest_lock(self.path):
            tx.recover_pending(self.path)
        self.assertEqual((self.base / "final/a.png").read_bytes(), b"old-a")
        self.assertEqual(p.read_json(self.path), self.manifest)
        self.assertEqual(self.finish(*self.start()), ("ok", 0))

    def test_ordinary_failure_code_commits_explicit_status(self):
        self.assertEqual(self.finish(*self.start(fail=True)), ("ok", 2))

    def test_interrupted_artifact_only_commit_rolls_back(self):
        process, release, results = self.start(crash=True, no_state=True)
        release.set()
        process.join(15)
        self.assertEqual(process.exitcode, 21)
        with manifest_lock(self.path):
            tx.recover_pending(self.path)
        self.assertEqual((self.base / "final/a.png").read_bytes(), b"old-a")
        self.assertFalse((self.base / "review/layouts/a.png").exists())

    def test_unselected_artifact_write_is_rejected(self):
        def operation(staged):
            (staged.parent / "final/b.png").write_bytes(b"wrong job")
            return 0
        with self.assertRaisesRegex(tx.TransactionConflict, "UNSCOPED_ARTIFACT_WRITE"):
            tx.run_staged_command(self.path, ["a"], operation, command_name="prepare")
        self.assertEqual((self.base / "final/b.png").read_bytes(), b"old-b")

    def test_prefix_overlapping_ids_have_distinct_artifact_owners(self):
        value = {"jobs": [{"id": "a"}, {"id": "a-b"}]}
        self.assertEqual(tx._artifact_owner("review/layouts/a-b.png", value), "a-b")

    def test_declared_unselected_revision_images_survive_staging(self):
        revision = self.base / "revision"
        revision.mkdir()
        (revision / "ear_detail.png").write_bytes(b"declared detail pixels")
        (revision / "bow_detail.png").write_bytes(b"declared bow pixels")
        (revision / "compare.html").write_text("old standalone report", encoding="utf-8")
        (revision / "archive.zip").write_bytes(b"old archive")
        (revision / "old-unreferenced.png").write_bytes(b"old image")
        self.manifest["jobs"][1]["layout"] = {"items": [{"image": "revision/ear_detail.png"},
                                                        {"image": "revision/bow_detail.png"}]}
        p.write_json(self.path, self.manifest)

        def operation(staged):
            self.assertEqual((staged.parent / "revision/ear_detail.png").read_bytes(), b"declared detail pixels")
            self.assertTrue((staged.parent / "revision/bow_detail.png").is_file())
            self.assertFalse((staged.parent / "revision/compare.html").exists())
            self.assertFalse((staged.parent / "revision/archive.zip").exists())
            self.assertFalse((staged.parent / "revision/old-unreferenced.png").exists())
            return 0

        tx.run_staged_command(self.path, ["a"], operation, command_name="prepare")
        self.assertEqual(p.read_json(self.path)["jobs"][1], self.manifest["jobs"][1])

    def test_declared_revision_input_cannot_be_modified_in_stage(self):
        (self.base / "revision").mkdir()
        source = self.base / "revision/detail.png"
        source.write_bytes(b"real source")
        self.manifest["jobs"][0]["layout"] = {"items": [{"image": "revision/detail.png"}]}
        p.write_json(self.path, self.manifest)

        def operation(staged):
            (staged.parent / "revision/detail.png").write_bytes(b"unexpected replacement")
            return 0

        with self.assertRaisesRegex(tx.TransactionConflict, "INPUT_ARTIFACT_WRITE"):
            tx.run_staged_command(self.path, ["a"], operation, command_name="prepare")
        self.assertEqual(source.read_bytes(), b"real source")

    def test_unselected_mutation_is_never_committed(self):
        def operation(staged):
            value = p.read_json(staged)
            value["jobs"][1]["status"] = "failed"
            p.write_json(staged, value)
            return 0
        with self.assertRaisesRegex(tx.TransactionConflict, "UNSCOPED_JOB_WRITE"):
            tx.run_staged_command(self.path, ["a"], operation, command_name="prepare")
        self.assertEqual(p.read_json(self.path), self.manifest)

    def test_noop_preserves_artifact_bytes_and_mtime(self):
        original = (self.base / "final/a.png").stat().st_mtime_ns
        tx.run_staged_command(self.path, ["a"], lambda _: 0, command_name="prepare")
        self.assertEqual(original, (self.base / "final/a.png").stat().st_mtime_ns)
        journal = next((self.base / tx._AREA).glob("*/journal.json"))
        metrics = p.read_json(journal)["metrics"]
        self.assertGreater(metrics["cloned_files"] + metrics["copied_bytes"], 0)
        self.assertIn("snapshot_seconds", metrics)

    def test_clone_never_shares_writable_inode(self):
        def operation(staged):
            (staged.parent / "raw/a.png").write_bytes(b"stage-only")
            self.assertEqual((self.base / "raw/a.png").read_bytes(), b"old-a")
            raise RuntimeError("cancel staged operation")
        with self.assertRaisesRegex(RuntimeError, "cancel"):
            tx.run_staged_command(self.path, ["a"], operation, command_name="compose")
        self.assertEqual((self.base / "raw/a.png").read_bytes(), b"old-a")

    def test_symlink_target_escape_rejected(self):
        with self.assertRaises(tx.TransactionConflict):
            tx._target(self.base, "../outside.png")
        with self.assertRaises(tx.TransactionConflict):
            tx._target(self.base, "/outside.png")

    def test_three_way_merge_preserves_delete_and_concurrent_fields(self):
        self.assertEqual(tx._merge({"a": 1, "b": 2}, {"a": 1, "b": 3}, {"b": 2}), {"b": 3})

    def test_real_pipeline_prepare_keeps_generation_fingerprints(self):
        from pipeline_test_support import create_v3_fixture, prepare_fixture, MAIN_ID
        base = self.base / "real-fixture"
        manifest = create_v3_fixture(base)
        prepare_fixture(manifest, base)
        path = base / "project_manifest.json"
        p.write_json(path, manifest)
        before = {job["id"]: job["prompt_hash"] for job in manifest["jobs"]}

        def operation(staged):
            value = p.read_json(staged)
            p.prepare(value, staged.parent, [MAIN_ID])
            p.write_json(staged, value)
            return 0

        tx.run_staged_command(path, [MAIN_ID], operation, command_name="prepare")
        after = p.read_json(path)
        self.assertEqual(before, {job["id"]: job["prompt_hash"] for job in after["jobs"]})
        self.assertEqual(manifest["jobs"][1], after["jobs"][1])

    def test_real_ingest_completes_while_other_job_heavy_stage_waits(self):
        from PIL import Image
        from lc_workflow import ingest
        from pipeline_test_support import create_v3_fixture, prepare_fixture, MAIN_ID, SECONDARY_ID, NOTE
        base = self.base / "real-ingest"
        manifest = create_v3_fixture(base)
        prepare_fixture(manifest, base)
        p.transition_job(manifest, SECONDARY_ID, "generating", NOTE, base)
        attempt = p.find_by_id(manifest["jobs"], SECONDARY_ID)["active_attempt_id"]
        path = base / "project_manifest.json"
        p.write_json(path, manifest)
        artifact = self.base / "synthetic-model-return.png"
        Image.new("RGB", (1600, 1600), "white").save(artifact)
        ready, release, results = self.context.Event(), self.context.Event(), self.context.Queue()
        process = self.context.Process(target=_worker, args=(str(path), MAIN_ID, ready, release, results))
        process.start()
        self.processes.append(process)
        self.assertTrue(ready.wait(10))
        started = time.monotonic()
        with manifest_lock(path, timeout=1):
            value = p.read_json(path)
            result = ingest(value, base, SECONDARY_ID, artifact, attempt)
            p.write_json(path, value)
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 1, f"real ingest blocked by heavy stage: {elapsed:.3f}s")
        self.assertEqual(result["status"], "generated")
        self.assertEqual(self.finish(process, release, results), ("ok", 0))
        self.assertEqual(p.find_by_id(p.read_json(path)["jobs"], SECONDARY_ID)["status"], "generated")


if __name__ == "__main__":
    unittest.main()
