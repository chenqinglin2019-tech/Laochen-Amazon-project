"""Regression coverage for workflow compaction and safe reuse."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from advance_work import actionable_packet, execute_sources
from assessment_estimate import _row_conflicts
from completion_check import workflow_stage
from record_independent_review import expand_pending
from common import atomic_write_json, load_json, now_iso, sha256_file
from runtime_v24 import _physical_request_identity, _reuse_physical_response


class WorkflowEfficiencyTests(unittest.TestCase):
    def test_external_limitation_does_not_preempt_independent_review(self):
        view = {"entries": [{"work_id": "W", "kind": "user_information", "state": "awaiting_user"}],
                "review_work": {"entries": []}}
        packet = actionable_packet(view)
        self.assertEqual(workflow_stage(view, packet, first_review=None, second_review=None,
                                        adjudication=None, output_dir=None), "independent_review")

    def test_api_rows_are_submitted_to_one_phase_batch(self):
        plan = {"queries": {
            "epo_ops": [{"query_id": "Q1", "execution_phase": "initial"}],
            "jpo_api": [{"query_id": "Q2", "execution_phase": "initial"}],
            "uspto_patent_browser": [{"query_id": "Q3", "execution_phase": "verification"}],
        }}
        entries = [{"query_id": value} for value in ("Q1", "Q2", "Q3")]
        completed = type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        with patch("advance_work.subprocess.run", return_value=completed) as run:
            execute_sources(Path("/tmp/task"), plan, entries)
        commands = [call.args[0] for call in run.call_args_list]
        api = [command for command in commands if command[1].endswith("run_api_plan.py")]
        self.assertEqual(len(api), 1)
        self.assertTrue({"Q1", "Q2"} <= set(api[0]))

    def test_display_title_difference_is_not_a_substantive_conflict(self):
        base = {"risk": "高", "evidence_confidence": "中", "module_id": "utility_patent",
                "comparison": {"implementations": [{"implementation_id": "I1", "title": "A",
                    "description": "same product configuration", "product_evidence_refs": ["EV1"]}],
                    "claims": []}}
        other = deepcopy(base)
        other["comparison"]["implementations"][0]["title"] = "Equivalent display title"
        self.assertNotIn("comparison:implementations", _row_conflicts(base, other,
                         {"decision_workflow_revision": "scenario-triage-v1"}))
        other["comparison"]["implementations"][0]["description"] = "different implementation"
        self.assertIn("comparison:implementations", _row_conflicts(base, other,
                      {"decision_workflow_revision": "scenario-triage-v1"}))

    def test_lens_wire_identity_ignores_logical_right_only(self):
        base = {"operation": "image_search", "jurisdiction": "US", "q": "https://example.test/a.jpg",
                "image_url": "https://example.test/a.jpg", "type": "all", "hl": "en", "country": "us"}
        self.assertEqual(_physical_request_identity("serpapi_google_lens", base | {"right_type": "design"}),
                         _physical_request_identity("serpapi_google_lens", base | {"right_type": "copyright"}))
        self.assertNotEqual(_physical_request_identity("serpapi_google_lens", base | {"right_type": "design"}),
                            _physical_request_identity("serpapi_google_lens", base | {"country": "gb"}))

    def test_lens_reuse_keeps_one_physical_source_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "lens.json"
            payload = {"search_metadata": {"status": "Success"}, "visual_matches": [{"title": "retained",
                "link": "https://example.test/work", "image": "https://example.test/a.jpg"}]}
            atomic_write_json(raw, payload)
            from serpapi_lens_client import normalize
            source = {"run_id": "RUN-1", "attempt_id": "RUN-1", "query_id": "Q1",
                "provider": "serpapi_google_lens", "operation": "image_search", "jurisdiction": "US",
                "right_type": "design", "status": "success", "submission_state": "submitted",
                "quota": {"network_request_attempted": True},
                "finished_at": now_iso(), "raw_paths": [str(raw)],
                "payload_digest": sha256_file(raw), "plan_entry_sha256": "old",
                "request_params": {"q": "https://m.media-amazon.com/images/I/fixture.jpg", "image_url": "https://m.media-amazon.com/images/I/fixture.jpg",
                    "type": "all", "hl": "en", "country": "us"}}
            evidence = {"source_runs": [source], "collections": {"copyright_assets": [{
                "evidence_id": "EV-1", "source_run_id": "RUN-1", "query_id": "Q1",
                "provider": "serpapi_google_lens", "operation": "image_search", "jurisdiction": "US",
                "right_type": "design", "plan_entry_sha256": "old", "payload": normalize(payload,
                    retrieval_workflow_revision="api-first-v3", investigation_right_type="design")}]}}
            atomic_write_json(root / "evidence.json", evidence)
            row = {"query_id": "Q2", "operation": "image_search", "jurisdiction": "US",
                "right_type": "copyright", "requirement_ids": ["R2"],
                "q": "https://m.media-amazon.com/images/I/fixture.jpg", "image_url": "https://m.media-amazon.com/images/I/fixture.jpg",
                "type": "all", "hl": "en", "country": "us"}
            task = {"retrieval_workflow_revision": "api-first-v3",
                    "images": [{"source_url": row["image_url"], "sha256": "fixture-image-digest"}]}
            params = {key: row[key] for key in ("q", "image_url", "type", "hl", "country", "right_type")}
            reused = _reuse_physical_response(root, "serpapi_google_lens", row, 48,
                authorized_task=task, authorized_params=params)
            self.assertIsNotNone(reused)
            self.assertFalse(reused["source_query_performed"])
            self.assertEqual(reused["metadata"]["physical_response_reuse"]["independent_source_count"], 1)
            saved = load_json(root / "evidence.json")
            copied = next(item for item in saved["collections"]["copyright_assets"] if item["query_id"] == "Q2")
            self.assertEqual(copied["physical_response_reuse"]["source_evidence_id"], "EV-1")

    def test_compact_pending_expands_without_assigning_risk(self):
        task = {"primary_scenario_id": "product_entry", "assessment_scenarios": [{
            "scenario_id": "product_entry", "title": "Product entry", "conditional": False,
            "assumptions": [], "right_types": ["patent"]}]}
        row = expand_pending({"scenario_id": "product_entry", "jurisdiction": "US",
                              "right_type": "patent", "assessment_status": "pending",
                              "pending_reasoning": "The current status source is unavailable."}, task)
        self.assertIsNone(row["risk"])
        self.assertEqual(row["evidence_confidence"], "低")
        self.assertEqual(row["supporting_evidence"], [])


if __name__ == "__main__":
    unittest.main()
