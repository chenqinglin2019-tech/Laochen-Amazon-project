"""Completed v2 artifacts are not delivered until independent file QA passes."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from common import atomic_write_bytes, load_json
from offline_test_support import isolated_test_environment
import report_estimate as report
from test_evidence_delivery_integration import build_evidence_delivery_fixture


class ReportDeliveryTransactionTests(unittest.TestCase):
    def setUp(self):
        self.environment = isolated_test_environment()
        self.environment.__enter__()
        self.addCleanup(self.environment.__exit__, None, None, None)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        result = build_evidence_delivery_fixture(self.root / "input")
        self.source = Path(result["directory"])
        self.published = Path(result["report"]).parent
        self.task = load_json(self.published / "task.json")
        self.assessment = load_json(self.published / "assessment.json")

    def build(self, destination):
        return report.build_bundle(self.source, self.task, load_json(self.source / "evidence.json"),
            self.assessment, load_json(self.source / "normalized-candidates.json"),
            {"schema_version": "1.0", "task_id": self.task["task_id"], "entries": []},
            load_json(self.source / "search-plan.json"), output_dir=destination)

    def test_readiness_is_separate_from_actual_validated_delivery(self):
        self.assertEqual(self.assessment["publication"]["delivery_status"], "ready")
        data = load_json(self.published / "report-data.json")
        self.assertEqual(data["publication"]["delivery_status"], "completed")
        self.assertEqual(report.validate_run(self.source, self.task, output_dir=self.published), [])
        destination = self.root / "standalone"
        data, manifest = self.build(destination)
        self.assertEqual(manifest["delivery_status"], "completed")
        self.assertEqual(report.validate_run(self.source, self.task, output_dir=destination), [])

    def test_failed_staging_validation_publishes_no_report_artifacts(self):
        original = report._write_bundle
        def corrupt_staged_html(data, out):
            result = original(data, out)
            atomic_write_bytes(out / "report.html", b"deliberately corrupted offline fixture")
            return result
        destination = self.root / "rejected"
        with patch.object(report, "_write_bundle", side_effect=corrupt_staged_html):
            with self.assertRaisesRegex(ValueError, "REPORT_DELIVERY_VALIDATION_FAILED.*REPORT_ARTIFACT_MISMATCH"):
                self.build(destination)
        for name in ("report.html", "report.md", "report-data.json", "report-findings.csv", "report-manifest.json"):
            self.assertFalse((destination / name).exists())
        self.assertEqual(report.validate_run(self.source, self.task, output_dir=self.published), [])


if __name__ == "__main__":
    unittest.main()
