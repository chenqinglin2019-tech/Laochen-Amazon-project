"""Unmocked original receipt/fact/triage integration; synthetic files only."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

from common import atomic_write_json, load_json, sha256_file, sha256_json
from provider_utils import sanitize_for_evidence
from record_browser_execution import planned_browser_query, validate_browser_execution
from record_tsdr_browser_verification import validate_common, normalize_success
from workflow_v24 import (append_candidate_actions, scenario_fact_reuse, scenario_dispatch_block,
                          bind_scenario_action)
from assessment_v24 import coverage_by_scope
from merge_candidates import candidate_verification_view, verification_index
import test_scenario_planning


class SameTaskEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.f = test_scenario_planning.ScenarioPlanningTests()
        self.f.setUp()
        self.addCleanup(self.f.tearDown)
        f = self.f
        self.date = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        params = {"q": f.candidate["serial_number"], "serial_number": f.candidate["serial_number"],
                  "candidate_id": f.candidate["candidate_id"]}
        f.annotate("needs_info", missing_information=["Official record"], next_actions=[{
            "action_id": "lookup", "kind": "source_lookup", "provider": "uspto_tsdr",
            "operation": "candidate_verification", "purpose": "Read official goods and status", "params": params, "max_attempts": 1,
            "required_facts": ["goods_services", "current_status"], "reading_scope": {"level": "goods_services"}}])
        append_candidate_actions(f.path, f.task, f.candidates)
        f.plan = load_json(f.path / "search-plan.json")
        self.source = f.plan["queries"]["uspto_tsdr"][0]
        shot = f.path / "screenshots" / "original.png"
        shot.parent.mkdir(exist_ok=True)
        # A byte-bound screenshot suffices here; tests do not assert live origin.
        atomic_write_json(shot, {"synthetic_pixel_fixture": 1})
        self.capture = {"query_id": self.source["query_id"], "candidate_id": f.candidate["candidate_id"],
            "status": "success", "serial_number": params["q"], "page_case_number": params["q"],
            "right_type": "trademark_word", "mark_text": "TEST", "owners": ["Test Owner"],
            "registration_number": "1234567", "case_status": "Registered", "goods_services": ["Straps"],
            "classes": ["021"], "goods_services_truncated": False, "browser": "chrome_desktop",
            "capture_transport": "cdp", "browser_version": "offline-fixture", "protocol_version": "1.3",
            "cdp_session_id": "offline-session", "checked_at": self.date, "screenshot_path": str(shot),
            "final_url": "https://tsdr.uspto.gov/#caseNumber=" + params["q"] + "&caseSearchType=US_APPLICATION&searchType=statusSearch",
            "query_semantics": planned_browser_query("uspto_tsdr", self.source, f.task)}
        self.receipt = {"task_id": f.task["task_id"], "provider": "uspto_tsdr", "query_id": self.source["query_id"],
            "operation": "candidate_verification", "jurisdiction": "US", "right_type": "trademark_word", "query": params["q"],
            "plan_entry_sha256": sha256_json(self.source), "mode": "automatic", "business_actions_by": "agent",
            "outcome": "success", "final_url": self.capture["final_url"], "completed_at": self.date,
            "query_semantics": self.capture["query_semantics"], "result_coverage_sha256": sha256_json({}),
            "media_coverage_sha256": sha256_json({}), "result_pages_sha256": sha256_json([]),
            "result_sha256": sha256_json({"record_number": params["q"], "page_record_number": params["q"]}),
            "events": [{"actor": "agent", "action": "navigate_record", "record_number": params["q"], "at": self.date},
                       {"actor": "agent", "action": "observe_result", "stable": True, "at": self.date,
                        "screenshot_sha256": sha256_file(shot)}]}
        self.receipt_path = f.path / "raw" / "browser-execution" / "original.json"
        self.original_path = f.path / ("uspto_tsdr-" + self.source["query_id"] + "-original-capture.json")
        self.raw = f.path / "raw" / "uspto_tsdr" / "original.json"
        self.write_capture()
        normalized = sanitize_for_evidence(normalize_success(self.capture,
            validate_common(self.capture, f.task, {"tsdr.uspto.gov"}, f.path, "success"), f.candidate["candidate_id"]))
        self.source_run = {"run_id": "R-ORIGINAL", "provider": "uspto_tsdr", "query_id": self.source["query_id"],
            "operation": "candidate_verification", "jurisdiction": "US", "right_type": "trademark_word",
            "query": params["q"], "request_params": {**params, "right_type": "trademark_word"},
            "requirement_ids": self.source["requirement_ids"], "plan_entry_sha256": sha256_json(self.source),
            "status": "success", "finished_at": self.date, "raw_paths": [str(self.raw)], "payload_digest": sha256_file(self.raw)}
        self.ev = {"evidence_id": "EV-ORIGINAL", "source_run_id": self.source_run["run_id"], "payload": normalized,
                   **{key: self.source_run[key] for key in ("provider", "query_id", "operation", "jurisdiction", "right_type", "requirement_ids", "plan_entry_sha256")}}
        f.evidence["source_runs"].append(self.source_run)
        f.evidence["collections"].setdefault("official_verifications", []).append(self.ev)
        f.candidate["verification_refs"] = ["EV-ORIGINAL"]
        f.candidate["evidence_refs"].append("EV-ORIGINAL")
        f.candidate.update(candidate_verification_view(f.task, "trademarks", f.candidate, f.evidence,
            verification_index(f.evidence["collections"]["official_verifications"])))
        f.annotate("selected")
        append_candidate_actions(f.path, f.task, f.candidates)
        f.plan = load_json(f.path / "search-plan.json")
        self.target = f.plan["queries"]["uspto_tsdr"][-1]
        f.save()

    def binding(self, path):
        return {"path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size}

    def write_capture(self):
        atomic_write_json(self.receipt_path, self.receipt)
        self.capture["query_execution"] = self.binding(self.receipt_path)
        atomic_write_json(self.original_path, self.capture)
        atomic_write_json(self.raw, sanitize_for_evidence(self.capture))
        if hasattr(self, "source_run"):
            self.source_run["payload_digest"] = sha256_file(self.raw)
            self.f.save()

    def reuse(self, task=None, supplement=None):
        f = self.f
        return scenario_fact_reuse(task or f.task, f.plan, f.evidence, f.candidates, f.ledger,
            "uspto_tsdr", self.target, task_dir=f.path, supplement=supplement)

    def test_original_needs_info_credit_preserves_receipt_and_stays_non_dispatchable(self):
        f = self.f
        before = {p: sha256_file(p) for p in f.path.rglob("*") if p.is_file()}
        result = self.reuse()
        self.assertIsNotNone(result)
        self.assertEqual(result["source_query_id"], self.source["query_id"])
        self.assertEqual(result["source_checked_at"], self.date)
        self.assertEqual(result["source_plan_entry_sha256"], sha256_json(self.source))
        self.assertEqual(result["evidence_refs"], ["EV-ORIGINAL"])
        self.assertEqual(result["status"], "fact_reused")
        self.assertFalse(result["source_query_performed"])
        self.assertIsNotNone(scenario_dispatch_block(f.task, f.plan, "uspto_tsdr", self.source, f.candidates, f.ledger, f.evidence))
        validate_browser_execution(self.capture, f.task, f.path, "uspto_tsdr")
        self.assertEqual(before, {p: sha256_file(p) for p in f.path.rglob("*") if p.is_file()})

    def test_scheduler_and_coverage_use_same_credit_without_source_run(self):
        f = self.f
        scopes = coverage_by_scope(f.task, f.evidence, f.candidates, f.plan, ledger=f.ledger)
        result = next(r for scope in scopes for r in scope["queries"] if r["query_id"] == self.target["query_id"])
        self.assertTrue(result["complete"])
        self.assertEqual(result["dispatch"], "fact_reused")
        from run_browser_plan import execute_plan
        before = deepcopy(f.evidence)
        output = execute_plan(f.path, query_id_filter=self.target["query_id"],
                              runner=lambda *_args, **_kwargs: self.fail("Reused fact dispatched to browser"))
        row = next(r for r in output["queries"] if r["query_id"] == self.target["query_id"])
        self.assertEqual(row["status"], "fact_reused")
        self.assertEqual(row["submission_state"], "not_submitted")
        self.assertEqual(before, load_json(f.path / "evidence.json"))

    def test_target_must_remain_selected_and_bound_to_unchanged_business_context(self):
        f = self.f
        output_task = deepcopy(f.task)
        output_task.update(state="incomplete", updated_at=self.date, history=[{"state": "incomplete"}], outputs={"assessment_json": "result"})
        self.assertIsNotNone(self.reuse(task=output_task))
        output_task.setdefault("request", {})["new_business_fact"] = "different use"
        self.assertIsNone(self.reuse(task=output_task))
        f.annotate("not_selected")
        self.assertIsNone(self.reuse())

    def test_changed_receipt_hash_screenshot_or_original_content_cannot_credit(self):
        self.receipt["plan_entry_sha256"] = "0" * 64
        self.write_capture()
        self.assertIsNone(self.reuse())
        self.receipt["plan_entry_sha256"] = sha256_json(self.source)
        self.write_capture()
        self.assertIsNotNone(self.reuse())
        Path(self.capture["screenshot_path"]).write_bytes(b"changed")
        self.assertIsNone(self.reuse())

    def test_complete_receipt_of_another_query_cannot_be_borrowed(self):
        from same_task_evidence import _capture
        other = {**deepcopy(self.source), "query_id": "OTHER-PLANNED"}
        self.f.plan["queries"]["uspto_tsdr"].append(other)
        atomic_write_json(self.f.path / "search-plan.json", self.f.plan)
        self.capture["query_id"] = other["query_id"]
        self.receipt.update(query_id=other["query_id"], plan_entry_sha256=sha256_json(other))
        self.write_capture()
        validate_browser_execution(self.capture, self.f.task, self.f.path, "uspto_tsdr")
        with self.assertRaisesRegex(ValueError, "ORIGINAL_CAPTURE_UNVERIFIED"):
            _capture(self.f.path, self.f.task, self.capture, self.source)

    def test_wrong_serial_candidate_country_right_and_missing_status_are_rejected(self):
        original = deepcopy(self.ev["payload"])
        for changes in ({"serial_number": "00000000"}, {"candidate_id": "OTHER"}, {"jurisdiction": "GB"},
                        {"right_type": "trademark_figurative"}, {"official_verification": {**original["official_verification"], "legal_status": ""}},
                        {"official_verification": {**original["official_verification"], "identity_match": False}},
                        {"goods_services": ["Unrelated invented goods"]}):
            with self.subTest(changes=changes):
                self.ev["payload"] = {**deepcopy(original), **changes}
                self.f.save()
                self.assertIsNone(self.reuse())
        self.ev["payload"] = original
        self.f.save()
        self.assertIsNotNone(self.reuse())

    def test_nonproduction_and_explicit_unknown_environment_fail_closed(self):
        for holder in (self.source_run, self.ev, self.capture, self.receipt):
            for marker in ("fixture", None, "unknown"):
                with self.subTest(holder=holder.get("query_id"), marker=marker):
                    holder["source_environment"] = marker
                    self.write_capture()
                    self.assertIsNone(self.reuse())
                    holder.pop("source_environment")
        self.write_capture()
        self.assertIsNotNone(self.reuse())

    def test_later_failure_and_stale_timestamp_do_not_hide_behind_old_success(self):
        self.f.evidence["source_runs"].append({**self.source_run, "run_id": "LATER", "status": "failed"})
        self.f.save()
        self.assertIsNone(self.reuse())
        self.f.evidence["source_runs"].pop()
        self.source_run["finished_at"] = "2020-01-01T00:00:00Z"
        self.f.save()
        self.assertIsNone(self.reuse())

    def test_finalize_build_validate_keeps_credit_after_output_task_metadata_changes(self):
        from annotate_materiality import apply_materiality_annotations
        from assessment_estimate import finalize, review_digest, validate_assessment
        from report_estimate import build_bundle, validate_run
        f = self.f
        apply_materiality_annotations(f.ledger, f.task["task_id"], f.candidates, task=f.task, evidence=f.evidence)
        atomic_write_json(f.path / "browser-candidate-journal.json", {})
        f.save()
        digest = review_digest(f.evidence, f.candidates, f.ledger, f.plan, f.task)
        for label in ("first", "second"):
            atomic_write_json(f.path / (label + ".json"), {"reviewer": label,
                "review_context": {"session_id": label, "evidence_digest": digest, "first_review_visible": False},
                "assessments": [], "coverage_confidence_cap": "低", "coverage_confidence_reasoning": "Synthetic incomplete scopes remain."})
        output = f.path / "stage-output"
        assessment = finalize(f.path, f.task, f.path / "first.json", f.path / "second.json", output_dir=output)
        output_task = load_json(output / "task.json")
        self.assertEqual(assessment["status"], "incomplete")
        self.assertEqual(validate_assessment(f.path, output_task, assessment), [])
        row = next(r for s in assessment["coverage"]["scopes"] for r in s["queries"] if r["query_id"] == self.target["query_id"])
        self.assertEqual(row["dispatch"], "fact_reused")
        journal = load_json(f.path / "browser-candidate-journal.json")
        build_bundle(f.path, output_task, f.evidence, assessment, f.candidates, journal, f.plan, output_dir=output)
        self.assertEqual(validate_run(f.path, output_task, output_dir=output), [])

    def test_original_publication_content_is_exact_and_never_current_state(self):
        from decision_workflow import make_annotation, effective_decision
        f = self.f
        patent = {"candidate_id": "PATENT-C1", "publication_number": "US11111111B2", "jurisdiction": "US",
                  "right_type": "patent", "title": "Synthetic strap", "evidence_refs": ["EV-PDF"]}
        f.candidates["patents"].append(patent)
        document = f.path / "document.pdf"
        atomic_write_json(document, {"synthetic_original_publication": "US11111111B2"})
        item = {"evidence_id": "EV-PDF", "kind": "patent_document", "publication_number": patent["publication_number"],
                "jurisdiction": "US", "right_type": "patent", "authority_scope": "published_document_only",
                **self.binding(document), "checked_at": self.date, "source_document": str(document)}
        supplement = {"schema": "IPR-EVIDENCE-SUPPLEMENT/1.0", "evidence_root": str(f.path), "evidence": [item]}
        annotation = make_annotation(f.task, "patents", patent, {"annotation_id": "PATENT-SELECTED", "decision": "selected",
            "scenario_id": "product_entry", "reason": "Read retained original", "reviewer": "offline-agent", "annotated_at": self.date,
            "reading_level": "independent_claims", "basis_summary": "Exact original claim read", "reopen_conditions": ["New claim version"],
            "evidence_refs": ["EV-PDF"]}, evidence=f.evidence, supplement=supplement)
        f.ledger["annotations"].append(annotation)
        decision = effective_decision(f.task, f.ledger, "patents", patent, "product_entry", "US", evidence=f.evidence, supplement=supplement)
        base = {**deepcopy(self.target), "q": patent["publication_number"], "record_number": patent["publication_number"],
                "candidate_id": patent["candidate_id"], "right_type": "patent"}
        base.pop("serial_number")
        row = bind_scenario_action(f.task, "uspto_patent_browser", base, purpose="document_content", decision=decision)
        f.plan["queries"].setdefault("uspto_patent_browser", []).append(row)
        atomic_write_json(f.path / "search-plan.json", f.plan)
        f.save()
        reuse = lambda: scenario_fact_reuse(f.task, f.plan, f.evidence, f.candidates, f.ledger,
            "uspto_patent_browser", row, supplement=supplement, task_dir=f.path)
        self.assertEqual(reuse()["authority_scope"], "published_document_only")
        original = deepcopy(item)
        item["publication_number"] = "US11111111A1"
        self.assertIsNone(reuse())
        item.clear(); item.update(original)
        row2 = bind_scenario_action(f.task, "uspto_patent_browser", base, purpose="official_verification", decision=decision)
        f.plan["queries"]["uspto_patent_browser"].append(row2)
        atomic_write_json(f.path / "search-plan.json", f.plan)
        self.assertIsNone(scenario_fact_reuse(f.task, f.plan, f.evidence, f.candidates, f.ledger,
            "uspto_patent_browser", row2, supplement=supplement, task_dir=f.path))


if __name__ == "__main__":
    unittest.main()
