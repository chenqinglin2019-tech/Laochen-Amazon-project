from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from common import atomic_write_json, sha256_file, sha256_json
from verify_recall_acceptance import evaluate_recall, publication_identity


class RecallAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        artifact = self.root / "synthetic-identity.txt"
        artifact.write_text("Offline synthetic identity fixture; not live evidence")
        self.oracle = {"schema": "IPR-RECALL-ORACLE/1.0", "asin": "B000000001",
            "jurisdiction": "US", "right_type": "design", "expected_publication_numbers": ["USD123456S1"],
            "identity_review": {"reviewer": "fixture", "reasoning": "Synthetic test only",
                "artifacts": [{"path": str(artifact), "sha256": sha256_file(artifact),
                               "source_url": "https://example.test/fixture"}]}}
        self.query = {"query_id": "Q", "operation": "design_recall", "jurisdiction": "US",
                      "right_type": "design", "q": "lid AND strap", "strategy": "boolean", "requirement_ids": []}
        self.run = {**self.query, "run_id": "R", "provider": "uspto_patent_browser",
                    "status": "success", "source_environment": "production", "plan_entry_sha256": sha256_json(self.query)}
        self.entry = {key: self.run[key] for key in
                      ("provider", "query_id", "operation", "jurisdiction", "right_type", "plan_entry_sha256", "requirement_ids")}
        self.entry.update(evidence_id="EV", source_run_id="R", payload={"candidates": [
            {"publication_number": "D0123456", "title": "Fixture strap", "right_type": "design"}]})
        self.candidate = {"candidate_id": "C", "publication_number": "USD123456S1",
                          "right_type": "design", "evidence_refs": ["EV"]}
        self.capture_query_id = "Q"
        self.final_url = "https://ppubs.uspto.gov/pubwebapp/"
        self.receipt_extra = {}

    def evaluate(self, valid_capture=True):
        self.run.update({key: self.query[key] for key in ("operation", "q", "strategy")})
        self.run["plan_entry_sha256"] = sha256_json(self.query)
        self.entry.update(operation=self.run["operation"], plan_entry_sha256=self.run["plan_entry_sha256"])
        receipt_path = self.root / "raw" / "browser-execution" / "receipt.json"
        atomic_write_json(receipt_path, {"final_url": self.final_url, "mode": "automatic",
            "business_actions_by": "agent", **self.receipt_extra})
        values = {
            "task": {"task_id": "T", "product": {"requested_asin": "B000000001"}},
            "search-plan": {"task_id": "T", "queries": {"uspto_patent_browser": [self.query]}},
            "evidence": {"task_id": "T", "source_runs": [self.run], "collections": {"patents": [self.entry]}},
            "normalized-candidates": {"task_id": "T", "patents": [self.candidate]},
            "browser-execution-status": {"task_id": "T", "queries": [{"query_id": "Q", "capture_path": str(self.root / "capture.json")}]},
            "capture": {**self.query, "query_id": self.capture_query_id, "final_url": self.final_url,
                "query_execution": {"path": str(receipt_path), "sha256": sha256_file(receipt_path)},
                "candidates": deepcopy(self.entry["payload"]["candidates"])}}
        for name, value in values.items():
            atomic_write_json(self.root / (name + ".json"), value)
        with patch("verify_recall_acceptance.completed_capture", return_value=valid_capture):
            return evaluate_recall(self.root, self.oracle)

    def test_publication_normalization(self):
        self.assertEqual(publication_identity("US D0123456 S1"), "USD123456")
        self.assertNotEqual(publication_identity("US123456B2"), "USD123456")

    def test_positive_case_requires_bound_original_hit(self):
        self.assertEqual(self.evaluate()["status"], "passed")
        self.entry["payload"]["candidates"][0]["publication_number"] = "USD999999S1"
        self.assertEqual(self.evaluate()["status"], "incomplete")

    def test_known_number_is_not_blind_recall(self):
        for operation, strategy, query in [("candidate_verification", "record_number", "USD123456S1"),
                ("design_recall", "boolean", "D123456.PN.")]:
            with self.subTest(operation=operation):
                self.query.update(operation=operation, strategy=strategy, q=query)
                self.assertEqual(self.evaluate()["status"], "incomplete")

    def test_failed_execution_or_invalid_capture_cannot_pass(self):
        self.assertEqual(self.evaluate(valid_capture=False)["status"], "incomplete")
        self.run["status"] = "failed"
        self.assertEqual(self.evaluate()["status"], "incomplete")

    def test_valid_other_query_capture_cannot_be_reused(self):
        self.capture_query_id = "OTHER-QUERY"
        self.assertEqual(self.evaluate()["status"], "incomplete")

    def test_test_source_cannot_pass_live_acceptance(self):
        for environment in ("fixture", "test", "sandbox", "simulation", "mock", "synthetic", None):
            with self.subTest(environment=environment):
                self.run["source_environment"] = environment
                self.assertEqual(self.evaluate()["status"], "incomplete")
        self.run["source_environment"] = "production"
        self.entry["test_only"] = True
        self.assertEqual(self.evaluate()["status"], "incomplete")

    def test_utility_cannot_substitute_for_design(self):
        self.candidate["right_type"] = "patent"
        self.assertEqual(self.evaluate()["status"], "incomplete")

    def test_unlabelled_normal_recorder_requires_live_origin_and_receipt(self):
        self.run.pop("source_environment")
        self.assertEqual(self.evaluate()["status"], "passed")
        self.assertEqual(self.evaluate(valid_capture=False)["status"], "incomplete")
        for url in ("https://example.test/", "http://ppubs.uspto.gov/", "https://ppubs.uspto.gov.example.test/"):
            self.final_url = url
            self.assertEqual(self.evaluate()["status"], "incomplete")
        self.final_url = "https://ppubs.uspto.gov/pubwebapp/"
        for taint in ({"fixture": True}, {"source_environment": None}, {"source_environment": "staging"}):
            self.receipt_extra = taint
            self.assertEqual(self.evaluate()["status"], "incomplete")

    def test_oracle_requires_verified_identity_artifacts(self):
        self.oracle["identity_review"]["artifacts"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "IDENTITY_ARTIFACT_INVALID"):
            self.evaluate()


if __name__ == "__main__":
    unittest.main()
