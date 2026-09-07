"""Scenario-bound investigations, not hypothetical competitor-photo licensing."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from common import sha256_file
from decision_workflow import default_assessment_scenarios
from record_asset_provenance import (asset_scope, applicable_assets, investigation_complete,
    validate_payload, SPECIALTY_REVISION, inventory_identity_sha256)
from workflow_v24 import build_coverage_requirements_v24, term_records


class AssetScopeTests(unittest.TestCase):
    def setUp(self):
        self.task = {"specialty_workflow_revision": SPECIALTY_REVISION,
            "decision_workflow_revision": "scenario-triage-v1", "primary_scenario_id": "product_entry",
            "assessment_scenarios": default_assessment_scenarios(), "product": {
                "input_role": "reference_product", "assets": [
                    {"asset_id": "photo", "usage": "reference_only", "right_types": ["copyright"], "scenario_ids": ["product_entry"], "scope_reasoning": "Reference photo only", "evidence_refs": ["EV-PRODUCT"]},
                    {"asset_id": "shape", "usage": "product_configuration", "right_types": ["copyright", "trade_dress"], "scenario_ids": ["product_entry"], "scope_reasoning": "Visible adopted shape", "evidence_refs": ["EV-PRODUCT"]},
                    {"asset_id": "pattern", "usage": "integrated_expression", "right_types": ["copyright"], "scenario_ids": ["product_entry"], "scope_reasoning": "Integrated art", "evidence_refs": ["EV-PRODUCT"]}],
                "asset_scope_review": {"status": "reviewed", "reviewer": "agent", "reasoning": "Actual inventory reviewed", "evidence_refs": ["EV-PRODUCT"]}}}
        self.task["product"]["asset_scope_review"]["inventory_identity_sha256"] = inventory_identity_sha256(self.task, "copyright")

    def test_reference_photo_excluded_but_shape_and_pattern_retained(self):
        self.assertEqual(asset_scope(self.task, "product_entry", "copyright")["asset_ids"], ["pattern", "shape"])
        self.assertEqual(asset_scope(self.task, "product_entry", "trade_dress")["asset_ids"], ["shape"])
        self.assertEqual(applicable_assets(self.task, "brand_reuse", "copyright"), [])

    def test_intended_photo_is_included_without_assuming_ownership(self):
        self.task["product"]["assets"][0]["usage"] = "intended_material"
        self.assertIn("photo", asset_scope(self.task, "product_entry", "copyright")["asset_ids"])
        self.assertNotIn("risk", self.task["product"]["assets"][0])

    def test_intended_packaging_cannot_disappear_into_reviewed_empty_scope(self):
        package = deepcopy(self.task["product"]["assets"][0])
        package.update(asset_id="package", usage="intended_packaging",
                       right_types=["copyright", "trade_dress"],
                       scope_reasoning="Packaging artwork and source-identifying presentation planned for use")
        self.task["product"]["assets"] = [package]
        self.task["product"]["asset_scope_review"]["inventory_identity_sha256"] = inventory_identity_sha256(self.task, "copyright")
        for right_type in ("copyright", "trade_dress"):
            with self.subTest(right_type=right_type):
                scope = asset_scope(self.task, "product_entry", right_type)
                self.assertTrue(scope["inventory_reviewed"])
                self.assertEqual(scope["asset_ids"], ["package"])

    def test_missing_inventory_is_not_reviewed_empty(self):
        self.task["product"].pop("asset_scope_review")
        self.assertFalse(asset_scope(self.task, "product_entry", "copyright")["inventory_reviewed"])

    def test_unknown_legal_fact_does_not_erase_completed_work(self):
        scope = asset_scope(self.task, "product_entry", "copyright")
        payload = {"scenario_id": "product_entry", "asset_scope_sha256": scope["scope_sha256"],
            "coverage_attestation": {"inventory_complete": True, "asset_ids": scope["asset_ids"], "reviewed_asset_ids": scope["asset_ids"]},
            "unresolved": ["No private licence supplied"], "outstanding_actions": [],
            "artifacts": [{"sha256": "abc"}], "investigation_steps": [{"step": "provenance", "status": "completed", "reasoning": "Public sources actually read", "artifact_sha256": ["abc"], "evidence_refs": ["EV-PRODUCT"]}]}
        registry = {"EV-PRODUCT": {"kind": "provenance_document", "source_url": "https://example.org/original", "path": "retained", "sha256": "abc"}}
        query = {"right_type": "copyright", "search_dimension": "provenance", "asset_scope_sha256": scope["scope_sha256"]}
        self.assertTrue(investigation_complete(self.task, payload, query, "product_entry", registry))
        self.assertFalse(investigation_complete(self.task, payload, query, "product_entry", {}))
        payload["outstanding_actions"] = [{"kind": "public_investigation", "action": "Read original page"}]
        self.assertFalse(investigation_complete(self.task, payload, query, "product_entry", registry))
        payload["outstanding_actions"] = []
        payload["investigation_steps"][0]["status"] = "not_applicable"
        self.assertFalse(investigation_complete(self.task, payload, query, "product_entry", registry))

    def test_empty_figurative_inventory_requires_actual_review(self):
        self.assertFalse(asset_scope(self.task, "brand_reuse", "trademark_figurative")["inventory_reviewed"])
        self.task["product"]["mark_inventory_review"] = deepcopy(self.task["product"]["asset_scope_review"])
        self.assertFalse(asset_scope(self.task, "brand_reuse", "trademark_figurative")["inventory_reviewed"])
        self.task["product"]["mark_inventory"] = []
        self.task["product"]["mark_inventory_review"]["inventory_identity_sha256"] = inventory_identity_sha256(self.task, "trademark_figurative")
        self.assertTrue(asset_scope(self.task, "brand_reuse", "trademark_figurative")["inventory_reviewed"])
        self.task["product"]["mark_inventory"] = [{"mark_id": "M", "scenario_ids": ["brand_reuse"], "form": "stylized_text", "graphic_description": "Observed styled lettering", "evidence_refs": ["EV-PRODUCT"]}]
        self.assertEqual(asset_scope(self.task, "brand_reuse", "trademark_figurative")["asset_ids"], ["M"])

    def test_visual_comparison_requires_media_not_execution_receipts(self):
        scope = asset_scope(self.task, "product_entry", "copyright")
        query = {"right_type": "copyright", "search_dimension": "visual_comparison", "asset_scope_sha256": scope["scope_sha256"]}
        payload = {"scenario_id": "product_entry", "asset_scope_sha256": scope["scope_sha256"],
            "coverage_attestation": {"inventory_complete": True, "asset_ids": scope["asset_ids"], "reviewed_asset_ids": scope["asset_ids"]},
            "outstanding_actions": [], "artifacts": [{"sha256": "media-hash"}],
            "investigation_steps": [{"step": "visual_comparison", "status": "completed", "reasoning": "Read the retained visual evidence",
                "evidence_refs": ["EV-PRODUCT"], "artifact_sha256": ["media-hash"]}]}
        excluded_payloads = [
            {"capture_provenance": {"query_execution": {"path": "receipt.json", "sha256": "media-hash"}}},
            {"capture_provenance": {"query_execution": {"path": "receipt.png", "sha256": "media-hash"}}},
            {"logs": [{"path": "capture.png", "sha256": "media-hash"}]},
            {"artifacts": [{"path": "response.json", "sha256": "media-hash"}]},
        ]
        for excluded in excluded_payloads:
            with self.subTest(excluded=excluded):
                self.assertFalse(investigation_complete(self.task, payload, query, "product_entry",
                    {"EV-PRODUCT": {"kind": "product_record", "payload": excluded}}))
        screenshot = {"EV-PRODUCT": {"kind": "product_record", "payload": {
            "browser_evidence": {"screenshot_path": "source.png", "screenshot_sha256": "media-hash"}}}}
        self.assertTrue(investigation_complete(self.task, payload, query, "product_entry", screenshot))
        screenshot["EV-PRODUCT"]["kind"] = "agent_review"
        self.assertFalse(investigation_complete(self.task, payload, query, "product_entry", screenshot))

    def test_incomplete_asset_cannot_disappear_into_reviewed_empty_scope(self):
        self.task["product"]["assets"] = [{"asset_id": "unknown"}]
        self.assertFalse(asset_scope(self.task, "product_entry", "copyright")["inventory_reviewed"])

    def test_invalid_scope_and_null_inventory_fail_closed(self):
        for field, value in (("scenario_ids", ["typo"]), ("scenario_ids", None), ("right_types", ["copryight"]), ("right_types", [])):
            task = deepcopy(self.task)
            task["product"]["assets"][1][field] = value
            task["product"]["asset_scope_review"]["inventory_identity_sha256"] = inventory_identity_sha256(task, "copyright")
            self.assertFalse(asset_scope(task, "product_entry", "copyright")["inventory_reviewed"], (field, value))
        self.task["product"]["assets"] = None
        self.assertFalse(asset_scope(self.task, "product_entry", "copyright")["inventory_reviewed"])
        self.task["product"]["asset_scope_review"] = None
        self.assertFalse(asset_scope(self.task, "product_entry", "copyright")["inventory_reviewed"])

    def test_plain_stylized_mark_can_have_no_applicable_code_but_not_fake_code_search(self):
        self.task["product"]["mark_inventory"] = [{"mark_id": "M", "form": "stylized_text", "scenario_ids": ["brand_reuse"],
            "graphic_description": "Legible typography, no figurative device", "evidence_refs": ["EV-PRODUCT"],
            "classification_review": {"status": "not_applicable", "design_codes": [], "reasoning": "Read actual logo and official code manual", "evidence_refs": ["EV-PRODUCT"]}}]
        self.task["product"]["mark_inventory_review"] = {"status": "reviewed", "reviewer": "agent", "reasoning": "Actual logo read", "evidence_refs": ["EV-PRODUCT"],
            "inventory_identity_sha256": inventory_identity_sha256(self.task, "trademark_figurative")}
        scope = asset_scope(self.task, "brand_reuse", "trademark_figurative")
        query = {"right_type": "trademark_figurative", "search_dimension": "classification", "asset_scope_sha256": scope["scope_sha256"]}
        payload = {"scenario_id": "brand_reuse", "asset_scope_sha256": scope["scope_sha256"],
            "coverage_attestation": {"inventory_complete": True, "asset_ids": ["M"], "reviewed_asset_ids": ["M"]},
            "outstanding_actions": [], "artifacts": [{"sha256": "abc"}], "investigation_steps": [{"step": "classification", "status": "not_applicable", "reasoning": "No supported code", "evidence_refs": ["EV-PRODUCT"], "artifact_sha256": ["abc"]}]}
        registry = {"EV-PRODUCT": {"kind": "provenance_document", "path": "original", "sha256": "abc"}}
        self.assertTrue(investigation_complete(self.task, payload, query, "brand_reuse", registry))
        payload["investigation_steps"][0]["status"] = "completed"
        self.assertFalse(investigation_complete(self.task, payload, query, "brand_reuse", registry))

    def test_requirement_revision_does_not_reinterpret_old_contract(self):
        old = build_coverage_requirements_v24(["US"])
        new = build_coverage_requirements_v24(["US"], specialty_workflow_revision=SPECIALTY_REVISION)
        get = lambda rows, right: next(row["required_axes"] for row in rows if row["right_type"] == right and row["phase"] in {"provenance", "official_recall"})
        self.assertEqual(get(old, "copyright"), ["provenance", "image"])
        self.assertEqual(get(new, "trade_dress"), ["public_use", "source_identification", "functionality"])
        self.assertEqual(get(new, "trademark_figurative"), ["classification", "description", "visual_comparison"])
        from provider_utils import coverage_route_policy
        from common import load_json
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([sys.executable, str(Path(__file__).with_name("create_task.py")), "--url", "https://www.amazon.com/dp/B012345678", "--jurisdictions", "US", "--output-dir", directory], check=True, capture_output=True)
            route_task = load_json(Path(directory) / "task.json")
            self.assertTrue(coverage_route_policy(route_task, "asset_provenance", "provenance_review", jurisdiction="US", right_type="trademark_figurative")[0])
            route_task.pop("specialty_workflow_revision")
            route_task["coverage_requirements"] = build_coverage_requirements_v24(route_task["target_jurisdictions"], screening_revision=route_task["screening_revision"])
            self.assertFalse(coverage_route_policy(route_task, "asset_provenance", "provenance_review", jurisdiction="US", right_type="trademark_figurative")[0])

    def test_fabricated_logo_term_cannot_be_scheduled(self):
        self.task["query_terms"] = [{"kind": "mark_description", "value": "bird", "language": "en", "derived_from": "product.mark_inventory[0]"}]
        with self.assertRaisesRegex(ValueError, "OBSERVED_MARK"):
            term_records(self.task)

    def test_scope_change_reopens_investigation(self):
        before = asset_scope(self.task, "product_entry", "copyright")["scope_sha256"]
        self.task["product"]["assets"][0]["usage"] = "intended_material"
        self.assertNotEqual(before, asset_scope(self.task, "product_entry", "copyright")["scope_sha256"])


if __name__ == "__main__":
    unittest.main()
