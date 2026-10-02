import tempfile
import unittest
import json
from unittest.mock import patch
from pathlib import Path

from common import atomic_write_json, load_json
from decision_workflow import default_assessment_scenarios
from record_product_analysis import validate_input, main


class ProductAnalysisRecorderTests(unittest.TestCase):
    def task(self):
        return {
            "schema_version": "2.4-free", "task_id": "T", "workflow_correction_revision": "workflow-correction-v1",
            "decision_workflow_revision": "scenario-triage-v1", "specialty_workflow_revision": "asset-scope-v1",
            "assessment_scenarios": default_assessment_scenarios(), "primary_scenario_id": "product_entry", "product": {"actual_asin": "B012345678", "assets": [], "mark_inventory": []},
            "images": [], "query_terms": [],
        }

    def payload(self):
        return {"product": {"structure": [{"description": "reusable pimple extractor skin", "language": "en"}],
            "assets": [{"asset_id": "shape", "usage": "product_configuration", "right_types": ["trade_dress"],
                        "scenario_ids": ["product_entry"], "scope_reasoning": "Visible adopted product shape", "evidence_refs": ["EV-PRODUCT"]}],
            "mark_inventory": []},
            "query_terms": [{"kind": "structural_feature", "value": "pimple extractor", "language": "en", "derived_from": "product.structure[0]"}]}

    def test_validates_before_planning_without_silently_dropping_asset(self):
        merged = validate_input(self.task(), self.payload())
        self.assertEqual(merged["product"]["assets"][0]["asset_id"], "shape")

    def test_rejects_unknown_scenario_and_unsupported_usage(self):
        payload = self.payload()
        payload["product"]["assets"][0]["scenario_ids"] = ["missing"]
        with self.assertRaisesRegex(ValueError, "scenario_ids"):
            validate_input(self.task(), payload)
        payload = self.payload()
        payload["product"]["assets"][0]["usage"] = "packaging_accessory"
        with self.assertRaisesRegex(ValueError, "usage"):
            validate_input(self.task(), payload)

    def test_partial_analysis_preserves_clue_dispositions_and_explicit_empty_clears(self):
        for supplied, expected in (({}, [{"source_path": "existing"}]),
                                   ({"clue_dispositions": []}, [])):
            with self.subTest(supplied=supplied), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                task = self.task()
                task["product"]["analysis"] = {"clue_dispositions": [{"source_path": "existing"}]}
                atomic_write_json(root / "task.json", task)
                payload = self.payload()
                payload["analysis"] = {"reviewer": "fixture", "reasoning": "Partial inventory review", **supplied}
                atomic_write_json(root / "input.json", payload)
                with patch("sys.argv", ["record_product_analysis", "--task-dir", directory,
                                         "--input", str(root / "input.json")]), \
                     patch("record_product_analysis.assert_active_free_policy"), \
                     patch("record_product_analysis.product_analysis_readiness", return_value={"ready": True}), \
                     patch("builtins.print"):
                    main()
                self.assertEqual(load_json(root / "task.json")["product"]["analysis"]["clue_dispositions"], expected)


if __name__ == "__main__":
    unittest.main()
