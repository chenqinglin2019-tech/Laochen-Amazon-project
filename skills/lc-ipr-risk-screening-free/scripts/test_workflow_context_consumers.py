"""Offline consumer agreement at the plan, dispatch and next-work boundaries."""
from argparse import Namespace
from copy import deepcopy
import unittest
from unittest.mock import patch

from common import atomic_write_bytes, atomic_write_json, load_json, now_iso, sha256_file
from annotate_materiality import _append_scenario_decisions
from run_browser_plan import _BatchInputs, record_failure
import runtime_v24
from workflow_v24 import append_candidate_actions, scenario_supplement, work_view_from_dir
import test_scenario_planning as fixtures


class WorkflowConsumerTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.ScenarioPlanningTests()
        self.f.setUp()
        self.addCleanup(self.f.tearDown)
        self.credentials = patch.object(runtime_v24, "credential", return_value=None)
        self.credentials.start()
        self.addCleanup(self.credentials.stop)
        f = self.f
        self.action = {"action_id": "MINIMAL-GOODS", "kind": "source_lookup", "purpose": "Read complete goods",
            "provider": "uspto_tsdr", "operation": "candidate_verification", "max_attempts": 1,
            "required_facts": ["goods_services"], "reading_scope": {"level": "goods_services"},
            "params": {"q": f.candidate["serial_number"], "serial_number": f.candidate["serial_number"],
                       "candidate_id": f.candidate["candidate_id"], "strategy": "record_number", "mode": "agent"}}
        f.annotate("needs_info", missing_information=["Full goods list"], next_actions=[self.action])

    def plan_action(self):
        f = self.f
        append_candidate_actions(f.path, f.task, f.candidates)
        f.plan = load_json(f.path / "search-plan.json")
        return f.plan["queries"]["uspto_tsdr"][0]

    def work(self, query_id, **kwargs):
        return next(item for item in work_view_from_dir(self.f.path, **kwargs)["entries"] if item.get("query_id") == query_id)

    def consumers(self, row):
        f = self.f
        return (lambda: scenario_supplement(f.path), lambda: work_view_from_dir(f.path),
                lambda: _BatchInputs(f.path).disposition("uspto_tsdr", row),
                lambda: _append_scenario_decisions(f.path, f.task, f.candidates, Namespace()))

    def test_present_invalid_default_is_rejected_by_all_consumers(self):
        row = self.plan_action()
        for invalid in ({}, [], None, {"schema": "test", "evidence": {}}):
            atomic_write_json(self.f.path / "supplemental-evidence.json", invalid)
            for consume in self.consumers(row):
                with self.subTest(invalid=invalid), self.assertRaises((ValueError, TypeError)):
                    consume()

    def test_broken_default_symlink_is_rejected_by_all_consumers(self):
        row = self.plan_action()
        (self.f.path / "supplemental-evidence.json").symlink_to(self.f.path / "missing.json")
        for consume in self.consumers(row):
            with self.assertRaises((ValueError, FileNotFoundError)):
                consume()

    def test_explicit_supplement_precedes_invalid_default(self):
        f = self.f
        atomic_write_json(f.path / "supplemental-evidence.json", {})
        explicit = f.path / "explicit.json"
        valid = {"schema": "IPR-EVIDENCE-SUPPLEMENT/1.0", "evidence": []}
        atomic_write_json(explicit, valid)
        self.assertEqual(scenario_supplement(f.path, explicit_path=explicit), valid)

    def test_existing_artifact_hash_is_rechecked_even_with_batch_decoder_reuse(self):
        row = self.plan_action()
        f = self.f
        source = f.path / "retained.txt"
        atomic_write_bytes(source, b"synthetic retained source")
        item = {"evidence_id": "EXTRA", "kind": "source_document", "path": str(source),
                "sha256": sha256_file(source), "bytes": source.stat().st_size, "checked_at": now_iso(),
                "source_url": "https://example.invalid/synthetic"}
        atomic_write_json(f.path / "supplemental-evidence.json", {"schema": "test", "evidence": [item]})
        batch = _BatchInputs(f.path)
        batch.disposition("uspto_tsdr", row)
        original = batch.decoded["supplemental-evidence.json"]
        batch.disposition("uspto_tsdr", row)
        self.assertIs(batch.decoded["supplemental-evidence.json"], original)
        atomic_write_bytes(source, b"tampered retained source")
        with self.assertRaisesRegex(ValueError, "HASH_OR_SIZE_MISMATCH"):
            batch.disposition("uspto_tsdr", row)

    def test_legacy_loader_keeps_empty_object_and_broken_link_semantics(self):
        task = deepcopy(self.f.task)
        task.pop("workflow_correction_revision")
        path = self.f.path / "supplemental-evidence.json"
        atomic_write_json(path, {})
        self.assertEqual(scenario_supplement(self.f.path, task=task), {})
        path.unlink()
        path.symlink_to(self.f.path / "missing.json")
        self.assertIsNone(scenario_supplement(self.f.path, task=task))

    def test_default_loader_checks_page_against_canonical_parent(self):
        from pypdf import PdfWriter
        f = self.f
        pdf = f.path / "canonical.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.write(pdf)
        parent = {"evidence_id": "PDF", "path": str(pdf), "sha256": sha256_file(pdf),
                  "publication_number": "USD123456S", "jurisdiction": "US", "right_type": "design"}
        f.evidence["collections"]["documents"] = [parent]
        f.save()
        image = f.path / "page.png"
        atomic_write_bytes(image, b"synthetic page bytes")
        page = {"evidence_id": "PAGE", "kind": "design_drawings", "path": str(image),
                "sha256": sha256_file(image), "bytes": image.stat().st_size, "checked_at": now_iso(),
                "source_document": str(pdf), "source_document_sha256": parent["sha256"],
                "page_number": 99, "page_verification": {"schema": "IPR-PDF-PAGE/1.0"}}
        atomic_write_json(f.path / "supplemental-evidence.json", {"schema": "test", "evidence": [page]})
        with self.assertRaisesRegex(ValueError, "PDF_PAGE_OUT_OF_RANGE"):
            scenario_supplement(f.path)

    def test_default_and_runtime_capability_views_agree_after_missing_credentials(self):
        f = self.f
        row = f.plan["queries"]["epo_ops"][0]
        caps = runtime_v24.capabilities(f.task, {})
        with patch.object(runtime_v24, "capabilities", return_value=caps), \
                patch.object(runtime_v24.subprocess, "run") as network:
            output = runtime_v24.execute_api_plan(f.path, include_optional=True, query_ids_filter=[row["query_id"]])
            expected = next(item for item in output["work_view"]["entries"] if item.get("query_id") == row["query_id"])
            actual = self.work(row["query_id"])
        network.assert_not_called()
        self.assertEqual(actual, expected)
        self.assertEqual((actual["state"], actual["reason"]), ("awaiting_access", "optional_credentials_missing"))
        self.assertEqual(actual["evidence_obligation_id"], row["evidence_obligation_id"])

    def test_unaccepted_browser_route_remains_agent_work_not_user_access(self):
        row = self.f.plan["queries"]["uspto_patent_browser"][0]
        item = self.work(row["query_id"])
        self.assertEqual(item["state"], "ready")
        self.assertEqual(item["reason"], "browser_adapter_requires_real_route_acceptance")

    def test_known_missing_browser_executor_is_blocked_even_when_capability_is_unvalidated(self):
        f = self.f
        row = f.plan["queries"]["uspto_patent_browser"][0]
        record_failure(f.path, f.task, "uspto_patent_browser", row, {"status": "access_limited",
            "error_code": "AUTOMATION_NOT_VALIDATED", "phase": "validate_route", "submission_state": "not_submitted"})
        item = self.work(row["query_id"])
        self.assertEqual((item["state"], item["reason"]), ("blocked", "AUTOMATION_NOT_VALIDATED"))

    def test_unplanned_needs_info_keeps_action_and_required_facts(self):
        entries = work_view_from_dir(self.f.path)["entries"]
        action = next(item for item in entries if item.get("action_id") == self.action["action_id"])
        self.assertEqual((action["kind"], action["state"], action["reason"]),
                         ("plan_repair", "ready", "NEEDS_INFO_ACTION_UNPLANNED"))
        self.assertEqual(action["action"], self.action)
        self.assertEqual(action["required_facts"], ["goods_services"])
        self.assertFalse(any(item["reason"] == "SUPPLEMENT_RETRIEVED_REVIEW_REQUIRED" for item in entries))

    def test_planned_needs_info_has_one_dispatch_entry_without_duplicate_repair(self):
        row = self.plan_action()
        items = [item for item in work_view_from_dir(self.f.path)["entries"] if item.get("action_id") == self.action["action_id"]]
        self.assertEqual(len(items), 1)
        self.assertEqual((items[0]["kind"], items[0]["query_id"]), ("source_lookup", row["query_id"]))

    def test_old_plan_for_same_action_id_does_not_hide_new_decision_work(self):
        self.plan_action()
        self.f.annotate("needs_info", missing_information=["Recheck corrected goods"], next_actions=[self.action],
                        basis_summary="The first source record was corrected")
        items = work_view_from_dir(self.f.path)["entries"]
        self.assertTrue(any(item.get("action_id") == self.action["action_id"]
                            and item["reason"] == "NEEDS_INFO_ACTION_UNPLANNED" for item in items))


if __name__ == "__main__":
    unittest.main()
