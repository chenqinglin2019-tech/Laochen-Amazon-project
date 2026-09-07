"""A plan cancellation is scheduling metadata, never source evidence."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from common import atomic_write_json, load_json, sha256_json
from assessment_v24 import query_coverage
from test_assessment_estimate_recall import strict_fixture
import runtime_v24 as runtime


class ApiCancellationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        task, evidence, candidates, plan, *_ = strict_fixture(self.path)
        self.task, self.plan, self.candidates = task, plan, candidates
        requirement = next(r for r in task["coverage_requirements"] if r["jurisdiction"] == "US"
                           and r["right_type"] == "patent" and r["phase"] == "official_recall")
        route = next(route for route in requirement["routes"] if route["provider"] == "epo_ops")
        self.row = {"query_id": "Q-CANCEL-API", "operation": route["operation"], "jurisdiction": "US",
                    "right_type": "patent", "requirement_ids": [requirement["requirement_id"]],
                    "q": 'pn=US* and ta="lid" and ta="strap"', "range": "1-25",
                    "execute_by_default": True, "required_for": "low_risk", "wave": 1,
                    "search_dimension": "text", "search_language": "en", "execution_phase": "initial"}
        plan["queries"] = {"epo_ops": [self.row]}
        plan["execution_dispositions"] = [{"query_id": self.row["query_id"], "plan_entry_sha256": sha256_json(self.row),
                                            "status": "cancelled", "reason": "This planned route was explicitly cancelled; no query result is claimed."}]
        atomic_write_json(self.path / "evidence.json", evidence)
        self.save()

    def tearDown(self):
        self.temp.cleanup()

    def save(self):
        atomic_write_json(self.path / "task.json", self.task)
        atomic_write_json(self.path / "search-plan.json", self.plan)

    def execute(self):
        with patch("runtime_v24.capabilities", return_value=[{"provider": "epo_ops", "executable": True}]), \
             patch("run_api_plan.command_for", return_value=["offline-provider"]) as command, \
             patch("runtime_v24.subprocess.run", return_value=subprocess.CompletedProcess([], 2,
                   '{"status":"access_limited","error_code":"OFFLINE_ONLY"}', "")) as network:
            output = runtime.execute_api_plan(self.path)
        return output, command, network

    def test_cancelled_api_never_dispatches_or_creates_source_response(self):
        original = (self.path / "evidence.json").read_bytes()
        original_plan = (self.path / "search-plan.json").read_bytes()
        output, command, network = self.execute()
        command.assert_not_called()
        network.assert_not_called()
        self.assertEqual(output["status"], "incomplete")
        self.assertEqual(output["counts"]["cancelled"], 1)
        self.assertEqual(output["counts"]["executed"], 0)
        self.assertNotIn("source_run_id", output["results"][0])
        self.assertEqual((self.path / "evidence.json").read_bytes(), original)
        self.assertEqual((self.path / "search-plan.json").read_bytes(), original_plan)
        self.assertFalse((self.path / "api-retry-claims.json").exists())
        self.assertFalse(query_coverage(load_json(self.path / "evidence.json"), self.candidates,
                         self.plan, "epo_ops", self.row, self.task)["complete"])

    def test_stale_cancellation_cannot_suppress_a_changed_query(self):
        self.row["q"] = 'pn=US* and ta="cover" and ta="retainer"'
        self.save()
        output, _, network = self.execute()
        network.assert_called_once()
        self.assertNotIn("cancelled", output["counts"])

    def test_historical_task_does_not_adopt_new_cancellation_semantics(self):
        from workflow_v24 import build_coverage_requirements_v24
        self.task.pop("screening_revision")
        self.plan.pop("screening_revision")
        self.task["coverage_requirements"] = build_coverage_requirements_v24(self.task["target_jurisdictions"])
        self.save()
        output, _, network = self.execute()
        network.assert_called_once()
        self.assertNotIn("cancelled", output["counts"])

    def test_blank_reason_is_not_a_valid_cancellation(self):
        self.plan["execution_dispositions"][0]["reason"] = "  "
        self.save()
        output, _, network = self.execute()
        network.assert_called_once()
        self.assertNotIn("cancelled", output["counts"])

    def test_cancellation_does_not_reuse_preexisting_response(self):
        evidence = load_json(self.path / "evidence.json")
        evidence["source_runs"].append({"run_id": "PAST", "provider": "epo_ops", "query_id": self.row["query_id"],
            "plan_entry_sha256": sha256_json(self.row), "status": "success"})
        atomic_write_json(self.path / "evidence.json", evidence)
        original = (self.path / "evidence.json").read_bytes()
        with patch("runtime_v24.source_files_complete", return_value=True) as retained, \
             patch("runtime_v24.source_fresh", return_value=True):
            output, _, network = self.execute()
        retained.assert_not_called()
        network.assert_not_called()
        self.assertEqual(output["results"][0]["dispatch"], "cancelled")
        self.assertEqual((self.path / "evidence.json").read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
