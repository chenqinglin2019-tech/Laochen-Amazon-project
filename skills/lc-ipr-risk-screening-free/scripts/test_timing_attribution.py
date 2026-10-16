import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import timing_attribution as ta


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def snapshot(root):
    return sorted((p.name, p.stat().st_size, p.stat().st_mtime_ns) for p in root.iterdir())


class TimingAttributionTests(unittest.TestCase):
    def make_run(self, root):
        write(root / "task.json", {"created_at": "2026-10-01T10:00:00Z", "history": [
            {"at": "2026-10-01T10:00:00Z", "state": "created"}]})
        write(root / "evidence.json", {"created_at": "2026-10-01T10:00:00Z", "source_runs": [
            {"run_id": "A", "started_at": "2026-10-01T10:01:00Z", "finished_at": "2026-10-01T10:01:30Z"},
            {"run_id": "B", "started_at": "2026-10-01T10:10:00Z", "finished_at": "2026-10-01T10:10:10Z"}],
            "result_dispositions": [{"position": i, "reviewed_at": "2026-10-01T10:05:00Z"} for i in range(1, 4)],
            "collections": {"patents": [{"payload": {"finished_at": "2026-10-01T09:00:00Z",
                                                      "candidates": [{"filed_at": "2020-01-01T00:00:00Z"}]}}]}})
        write(root / "materiality-annotations.json", {"annotations": [
            {"annotated_at": "2026-10-01T10:20:00Z"}, {"annotated_at": "2026-10-01T10:21:00Z"}]})
        (root / ta.TIMINGS).write_text(json.dumps({"schema": "IPR-RUNTIME-TIMING/1.0", "stage": "visual_triage",
            "elapsed_ms": 60000, "started_at": "2026-10-01T10:11:00Z", "finished_at": "2026-10-01T10:12:00Z",
            "status": "success", "auxiliary_only": True}) + "\n", encoding="utf-8")

    def test_parse_accepts_full_datetimes_only(self):
        self.assertIsNotNone(ta.parse_ts("2026-10-01T10:00:00Z"))
        self.assertIsNotNone(ta.parse_ts("2026-10-01T10:00:00+08:00"))
        self.assertIsNotNone(ta.parse_ts("2026-10-01T10:00:00"))
        self.assertIsNone(ta.parse_ts("2026-10-01"))
        self.assertIsNone(ta.parse_ts("not a time"))
        self.assertIsNone(ta.parse_ts(None))

    def test_machine_and_authoring_time_are_separated(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.make_run(root)
            result = ta.analyse(root, idle_cap=900)
        self.assertEqual(result["wall_seconds"], 21 * 60)
        # Two source runs (30 s + 10 s) plus one timed 60 s step: no overlap.
        self.assertEqual(result["machine_seconds_union"], 100.0)
        kinds = {row["label"]: row for row in result["by_record_kind"]}
        dispositions = kinds["evidence.json:result_dispositions[]"]
        self.assertEqual(dispositions["events"], 3)
        # The batch of three shares one timestamp: the preceding gap lands once.
        self.assertGreater(dispositions["agent_seconds"] + dispositions["machine_seconds"], 0)
        annotations = kinds["materiality-annotations.json:annotations[]"]
        self.assertEqual(annotations["events"], 2)
        self.assertEqual(result["timed_steps_by_stage"][0]["stage"], "visual_triage")
        self.assertAlmostEqual(result["agent_or_harness_seconds"] + result["machine_seconds_union"],
                               result["active_seconds"], delta=1.0)

    def test_original_payload_timestamps_are_not_run_events(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.make_run(root)
            result = ta.analyse(root)
        self.assertNotIn("2026-10-01T09:00:00", result["first_event"])
        self.assertFalse(any("payload" in row["label"] for row in result["by_record_kind"]))

    def test_idle_gap_is_capped_and_reported_separately(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write(root / "task.json", {"created_at": "2026-10-01T10:00:00Z"})
            write(root / "ledger.json", {"rows": [{"recorded_at": "2026-10-01T10:00:10Z"},
                                                  {"recorded_at": "2026-10-01T12:00:10Z"}]})
            result = ta.analyse(root, idle_cap=300)
        self.assertEqual(result["wall_seconds"], 2 * 3600 + 10)
        self.assertEqual(result["idle_over_cap_seconds"], 2 * 3600 - 300)
        self.assertEqual(result["active_seconds"], 10 + 300)

    def test_read_only_and_credential_files_are_ignored(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.make_run(root)
            (root / ".env").write_text("SERPER_API_KEY=sentinel-secret\n", encoding="utf-8")
            write(root / "config.json", {"backend_token": "sentinel-secret", "created_at": "2026-10-01T10:30:00Z"})
            before = snapshot(root)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = ta.main(["--run-dir", str(root), "--json"])
            after = snapshot(root)
        self.assertEqual(code, 0)
        self.assertEqual(before, after)
        self.assertNotIn("sentinel-secret", out.getvalue())
        self.assertNotIn("config.json", out.getvalue())
        self.assertIsInstance(json.loads(out.getvalue()), dict)

    def test_plan_duplicates_and_lens_country_fanout(self):
        plan = {"queries": {
            "serpapi_google_lens": [
                {"query_id": "Q1", "operation": "image_search", "jurisdiction": "US",
                 "params": {"image_url": "https://example.test/a.jpg", "country": "us", "hl": "en"}},
                {"query_id": "Q2", "operation": "image_search", "jurisdiction": "DE",
                 "params": {"image_url": "https://example.test/a.jpg", "country": "de", "hl": "de"}}],
            "serper_patents": [
                {"query_id": "Q3", "operation": "search", "jurisdiction": "US", "params": {"q": "towel", "gl": "us"}},
                {"query_id": "Q4", "operation": "search", "jurisdiction": "US", "params": {"q": "towel", "gl": "us"}}]}}
        result = ta.plan_duplicates(plan)
        self.assertEqual(result["plan_rows"], 4)
        self.assertEqual(result["exact_duplicate_rows"], 1)
        self.assertEqual(result["same_request_other_country_rows"], 2)
        self.assertEqual(result["lens"], {"rows": 2, "countries": ["de", "us"], "distinct_images": 1})

    def test_missing_directory_and_bad_cap_are_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaises(SystemExit):
                ta.analyse(Path(raw) / "missing")
            with self.assertRaises(SystemExit):
                with contextlib.redirect_stderr(io.StringIO()):
                    ta.main(["--run-dir", raw, "--idle-cap", "0"])

    def test_empty_directory_reports_no_timestamps(self):
        with tempfile.TemporaryDirectory() as raw:
            result = ta.analyse(Path(raw))
        self.assertEqual(result["error"], "NO_TIMESTAMPS_FOUND")


if __name__ == "__main__":
    unittest.main()
