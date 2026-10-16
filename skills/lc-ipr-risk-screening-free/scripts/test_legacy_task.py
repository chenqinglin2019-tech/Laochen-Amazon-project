"""A task created before best-estimate-risk-v2 is reported, not silently continued under the new skill."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("LC_IPR_OFFLINE_TESTS", "1")

OLD = {"task_id": "IPRF-old", "created_at": "2026-10-10T17:12:57Z", "assessment_revision": "known-findings-risk-v1",
       "best_estimate_revision": None, "target_jurisdictions": ["US"],
       "request": {"url": "https://www.amazon.com/dp/B07HQL3SPZ"}}
NEW = {**OLD, "best_estimate_revision": "best-estimate-risk-v2"}


class NoticeTests(unittest.TestCase):
    def test_old_and_v1_tasks_get_a_notice_with_the_pipeline_command(self):
        from legacy_task import notice
        for task in (OLD, {**OLD, "best_estimate_revision": "best-estimate-risk-v1"}):
            value = notice(task)
            self.assertEqual(value["code"], "LEGACY_TASK_POLICY")
            self.assertIn("run_pipeline.py", value["recommended_command"])
            self.assertIn("https://www.amazon.com/dp/B07HQL3SPZ", value["recommended_command"])
            self.assertIn("--jurisdictions US", value["recommended_command"])
        self.assertIsNone(notice(NEW))
        self.assertIsNone(notice(None))


class PipelineGateTests(unittest.TestCase):
    def run_main(self, task, *extra):
        import run_pipeline
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "task.json").write_text(json.dumps(task), encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = run_pipeline.main(["--task-dir", tmp, "--resume", "--chief", "C", *extra])
            return code, out.getvalue()

    def test_resuming_an_old_task_is_refused_with_the_new_task_command(self):
        code, text = self.run_main(OLD)
        self.assertEqual(code, 1)
        result = json.loads(text)
        self.assertEqual(result["error_code"], "LEGACY_TASK_POLICY")
        self.assertIn("--allow-legacy", result["resume"])

    def test_dry_run_shows_the_notice(self):
        code, text = self.run_main(OLD, "--dry-run")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(text)["legacy_task"]["code"], "LEGACY_TASK_POLICY")
        code, text = self.run_main(NEW, "--dry-run")
        self.assertNotIn("legacy_task", json.loads(text))


if __name__ == "__main__":
    unittest.main()
