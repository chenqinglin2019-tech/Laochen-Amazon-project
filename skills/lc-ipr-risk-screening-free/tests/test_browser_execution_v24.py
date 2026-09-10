"""Regression tests for rejecting unbound/manual 2.4 browser evidence."""
import hashlib
import base64
import json
from pathlib import Path
import sys
import tempfile
import subprocess
import unittest
from copy import deepcopy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from common import now_iso, atomic_write_json, load_json, sha256_file
from record_browser_execution import canonical_digest, compile_ppubs_query, planned_browser_query, validate_browser_execution
from record_patent_browser_recall import capture_diagnostics, normalize_candidate
from record_uspto_patent_chrome_verification import normalize_success, repair_derived_request_params


class BrowserExecutionTests(unittest.TestCase):
    def test_recall_metadata_survives_recorder_and_merge_without_promoting_status(self):
        from merge_candidates import merge
        source = {"publication_number": "US11401089B2", "title": "Lid securing device", "jurisdiction": "US",
                  "right_type": "patent", "publication_date": "2022-08-02", "inventors": ["Armanda Hughes", "Cameron Hughes"],
                  "result_ordinal": 2, "family_id": "68160905", "family_member_count": 2,
                  "family_members": ["US20190315539A1", "US11401089B2"]}
        normalized = normalize_candidate(source, "uspto_patent_browser", "https://ppubs.uspto.gov/pubwebapp/", now_iso(), str(self.screenshot), sha256_file(self.screenshot), self.screenshot.stat().st_size)
        merged = merge("patent", [{"provider": "uspto_patent_browser", "evidence_id": "EV-metadata", "payload": {"candidates": [normalized]}}], {})[0]
        for field in ("publication_date", "inventors", "result_ordinal", "family_members", "family_member_count"):
            self.assertEqual(merged[field], source[field])
        self.assertEqual(merged["official_verification"]["status"], "not_checked")
        self.assertFalse(merged["material"])
        invalid = normalize_candidate({**source, "result_ordinal": True, "family_member_count": -1}, "uspto_patent_browser", "https://ppubs.uspto.gov/", now_iso(), "fixture", "digest", 1)
        self.assertIsNone(invalid["result_ordinal"])
        self.assertIsNone(invalid["family_member_count"])

    def test_published_recorder_merge_and_assessment_validation_keep_complete_plan_params(self):
        """Run real local entrypoints with synthetic evidence; no website/mock acceptance."""
        from assessment_estimate import validate_inputs
        from annotate_materiality import empty_materiality_ledger
        from merge_candidates import apply_candidate_contract
        skill = Path(__file__).resolve().parents[1]
        root = self.root / "pipeline"
        def command(*arguments):
            result = subprocess.run([sys.executable, *map(str, arguments)], capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            return result.stdout
        command(skill / "scripts/create_task.py", "--url", "https://www.amazon.com/dp/B000000001", "--jurisdictions", "US", "--output-dir", root)
        task = load_json(root / "task.json")
        task.pop("assessment_revision", None)  # This test pins the historical rating contract.
        task.pop("decision_workflow_revision", None)  # Frozen receipt contract predates scenario actions.
        task.pop("recall_planning_revision", None)
        task.pop("specialty_workflow_revision", None)
        task.pop("workflow_correction_revision", None)  # This fixture explicitly tests the frozen pre-correction recorder.
        task.pop("retrieval_workflow_revision", None)
        task.pop("retrieval_policy", None)
        from common import serper_free_enhancement, serpapi_free_enhancement
        task["serper_free_enhancement"] = serper_free_enhancement(False)
        task["serpapi_free_enhancement"] = serpapi_free_enhancement(False)
        from workflow_v24 import build_coverage_requirements_v24
        task["coverage_requirements"] = build_coverage_requirements_v24(task["target_jurisdictions"], screening_revision=task.get("screening_revision"))
        task["state"] = "incomplete"
        atomic_write_json(root / "task.json", task)
        atomic_write_json(root / "materiality-annotations.json", empty_materiality_ledger(task["task_id"]))
        subject = {"record_number": "USD123456S", "publication_number": "USD123456S", "title": "Fixture lid strap", "jurisdiction": "US", "right_type": "design"}
        apply_candidate_contract("patent", [subject])
        query = {"query_id": "Q-FIXTURE-DOCUMENT", "operation": "candidate_verification", "q": "USD123456S", "record_number": "USD123456S",
                 "candidate_id": subject["candidate_id"], "jurisdiction": "US", "right_type": "design", "strategy": "record_number",
                 "requirement_ids": ["COV-US-DESIGN-VERIFY"], "required": True, "wave": 2,
                 "search_dimension": "identity", "search_language": "en", "execution_phase": "expansion", "publication_scope": "published_document_only"}
        plan = {key: task[key] for key in ("schema_version", "task_id", "free_policy", "free_policy_revision", "screening_revision", "assessment_policy",
                                          "serper_free_enhancement", "serpapi_free_enhancement", "signa_free_enhancement", "execution_policy")}
        plan["queries"] = {"uspto_patent_browser": [query]}
        plan["execution_policy"] = {**plan["execution_policy"], "commercial_freemium_allowlist": [], "commercial_providers_enabled": False, "paid_execution_enabled": False}
        atomic_write_json(root / "search-plan.json", plan)
        screenshot = root / "screenshots" / "fixture-document.png"
        screenshot.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD1cAAAAASUVORK5CYII="))
        digest, at = sha256_file(screenshot), now_iso()
        semantics = planned_browser_query("uspto_patent_browser", query, task)
        capture = {"browser": "chrome_desktop", "capture_transport": "cdp", "browser_version": "Chrome-fixture", "protocol_version": "1.3", "cdp_session_id": "fixture_session",
                   "source_environment": "fixture", "status": "access_limited", "error_code": "MISSING_OFFICIAL_CURRENT_STATUS", "phase": "verify_current_status", "submission_state": "submitted",
                   "query_id": query["query_id"], "candidate_id": subject["candidate_id"], "record_number": "USD123456S", "page_record_number": "USD123456S",
                   "right_type": "design", "title": subject["title"], "classifications": ["D7/391"], "rendered_text": "Fixture ornamental strap publication.",
                   "final_url": "https://ppubs.uspto.gov/pubwebapp/", "checked_at": at, "screenshot_path": str(screenshot), "query_semantics": semantics,
                   "evidence_images": [{"path": str(screenshot), "role": "official_document_page"}],
                   "document_retrieval": {"status": "success", "authority_scope": "published_document_only", "identity_match": True, "record_number": "USD123456S",
                       "title": subject["title"], "rendered_text_sha256": canonical_digest("Fixture ornamental strap publication."),
                       "document_pages": [{"record_number": "USD123456S", "page": 1, "total_pages": 1, "path": str(screenshot), "sha256": digest}]}}
        events = [{"action": "submit_query", "actor": "agent", "at": at, "rendered_query": semantics["rendered_query"], "input_value": semantics["rendered_query"]},
                  {"action": "observe_query_binding", "actor": "agent", "at": at, "query": semantics["rendered_query"], "result_set_id": "L1", "screenshot_path": str(screenshot), "screenshot_sha256": digest},
                  {"action": "observe_result", "actor": "agent", "at": at, "stable": True, "identity": "USD123456S", "screenshot_sha256": digest}]
        js = "import {executionReceipt} from './tools/cdp/cdp-cli.mjs'; let raw=''; for await (const c of process.stdin) raw+=c; const x=JSON.parse(raw); console.log(JSON.stringify(executionReceipt(x.task,'uspto_patent_browser',x.query,x.events,x.capture)));"
        result = subprocess.run(["node", "--input-type=module", "-e", js], cwd=skill, input=json.dumps({"task": task, "query": query, "events": events, "capture": capture}), capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = root / "raw/browser-execution/fixture-receipt.json"
        atomic_write_json(receipt, json.loads(result.stdout))
        capture["query_execution"] = {"path": str(receipt), "sha256": sha256_file(receipt)}
        capture_path = root / "fixture-capture.json"
        atomic_write_json(capture_path, capture)
        command(skill / "scripts/record_uspto_patent_chrome_verification.py", "--task-dir", root, "--capture", capture_path)
        command(skill / "scripts/merge_candidates.py", "--task-dir", root)
        task, evidence, candidates, plan = [load_json(root / name) for name in ("task.json", "evidence.json", "normalized-candidates.json", "search-plan.json")]
        ledger = empty_materiality_ledger(task["task_id"])
        validate_inputs(task, evidence, candidates, plan, ledger, evidence_root=root)
        run = evidence["source_runs"][-1]
        self.assertEqual(run["request_params"]["strategy"], "record_number")
        self.assertNotIn("search_dimension", run["request_params"])
        self.assertEqual(candidates["patents"][0]["official_verification"]["status"], "incomplete")
        self.assertEqual(task["state"], "incomplete")
        # Reproduce the old serializer omission, prove the full final gate
        # rejects it, then exercise the audited, receipt-validated repair.
        del run["request_params"]["strategy"]
        atomic_write_json(root / "evidence.json", evidence)
        with self.assertRaisesRegex(ValueError, "OFFICIAL_VERIFICATION_PLAN_BINDING_INVALID"):
            validate_inputs(task, evidence, candidates, plan, ledger, evidence_root=root)
        evidence_id = evidence["collections"]["official_verifications"][0]["evidence_id"]
        protected = {str(file): sha256_file(file) for file in (screenshot, receipt, capture_path, Path(run["raw_paths"][0]))}
        repaired = repair_derived_request_params(root, [evidence_id])
        audit = load_json(Path(repaired["audit_path"]))
        self.assertFalse(audit["external_execution_performed"])
        self.assertTrue(Path(audit["snapshot_path"]).is_file())
        self.assertEqual(audit["changes"][0]["added_keys"], ["strategy"])
        self.assertEqual(protected, {file: sha256_file(Path(file)) for file in protected})
        validate_inputs(task, load_json(root / "evidence.json"), candidates, plan, ledger, evidence_root=root)
        with self.assertRaisesRegex(ValueError, "already match"):
            repair_derived_request_params(root, [evidence_id])

    def test_published_only_verification_retains_content_but_never_current_status(self):
        capture = {"title": "Lid strap", "right_type": "design", "candidate_id": "C1", "record_number": "USD123456S",
                   "page_record_number": "USD123456S", "classifications": ["D7/391"], "rendered_text": "An ornamental strap.",
                   "inventor_information": "Inventor; Test", "document_retrieval": {"status": "success", "authority_scope": "published_document_only"}}
        common = ("USD123456S", "https://ppubs.uspto.gov/pubwebapp/", now_iso(), str(self.screenshot),
                  hashlib.sha256(self.screenshot.read_bytes()).hexdigest(), {"capture_transport": "cdp"})
        result = normalize_success(capture, common, published_only=True)
        self.assertEqual(result["official_verification"]["status"], "incomplete")
        self.assertEqual(result["published_document"]["rendered_text"], capture["rendered_text"])
        self.assertEqual(result["legal_status"], "")
        self.assertEqual(result["owners"], [])
        self.assertTrue(result["official_verification"]["missing_official_current_status"])
        with self.assertRaisesRegex(ValueError, "does not establish"):
            normalize_success({**capture, "legal_status": "Active"}, common, published_only=True)
        with self.assertRaisesRegex(ValueError, "title and legal_status"):
            normalize_success(capture, common)

    def test_published_document_access_limited_still_requires_query_and_exact_identity(self):
        self.task["screening_revision"] = "recall-integrity-v1"
        self.provider = "uspto_patent_browser"
        self.entry.update(q="USD123456S", strategy="record_number", operation="candidate_verification", right_type="design")
        (self.root / "search-plan.json").write_text(json.dumps({"queries": {self.provider: [self.entry]}}))
        semantics = planned_browser_query(self.provider, self.entry, self.task)
        self.capture.pop("candidates")
        self.capture.update(status="access_limited", query_semantics=semantics, record_number="USD123456S", page_record_number="USD123456S",
                            title="Lid strap", rendered_text="Ornamental strap", document_retrieval={"status": "success", "authority_scope": "published_document_only",
                            "identity_match": True, "record_number": "USD123456S", "title": "Lid strap", "rendered_text_sha256": canonical_digest("Ornamental strap"), "document_pages": []})
        self.receipt.update(provider=self.provider, operation="candidate_verification", right_type="design", query=self.entry["q"], outcome="access_limited",
                            plan_entry_sha256=canonical_digest(self.entry), query_semantics=semantics, result_pages_sha256=canonical_digest([]),
                            document_retrieval_sha256=canonical_digest(self.capture["document_retrieval"]),
                            result_sha256=canonical_digest({"record_number": "USD123456S", "page_record_number": "USD123456S"}))
        self.receipt["events"][0].update(rendered_query=semantics["rendered_query"], input_value=semantics["rendered_query"])
        self.receipt["events"].insert(1, {"action": "observe_query_binding", "actor": "agent", "at": now_iso(), "result_set_id": "L1", "query": semantics["rendered_query"],
                                        "screenshot_path": str(self.screenshot), "screenshot_sha256": hashlib.sha256(self.screenshot.read_bytes()).hexdigest()})
        self.receipt["events"][-1]["identity"] = "USD123456S"
        self.write_receipt()
        self.validate()
        self.capture["page_record_number"] = "USD999999S"
        self.receipt["result_sha256"] = canonical_digest({"record_number": "USD123456S", "page_record_number": "USD999999S"})
        self.write_receipt()
        with self.assertRaisesRegex(ValueError, "document identity or text differs"):
            self.validate()

    def test_recorder_retains_specific_pre_submit_failure_diagnostics(self):
        diagnostics = {"error_code": "AUTOMATIC_QUERY_INPUT_MISMATCH", "phase": "prepare_input", "submission_state": "not_submitted"}
        self.assertEqual(capture_diagnostics({"status": "failed", **diagnostics}), diagnostics)

    def prepare_strict_ppubs_recall(self):
        """Shared synthetic strict receipt, query-history and viewport fixture."""
        self.task["screening_revision"] = "recall-integrity-v1"
        self.provider = "uspto_patent_browser"
        self.entry.update(q="lid AND strap", strategy="boolean", operation="design_recall", right_type="design")
        (self.root / "search-plan.json").write_text(json.dumps({"queries": {self.provider: [self.entry]}}))
        self.screenshot.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD1cAAAAASUVORK5CYII="))
        query = planned_browser_query(self.provider, self.entry, self.task)
        image_hash = hashlib.sha256(self.screenshot.read_bytes()).hexdigest()
        self.capture.update(result_set_id="L1", query_semantics=query, candidates=[{"record_number": "USD123456S"}],
                            final_url="https://ppubs.uspto.gov/pubwebapp/", right_type="design",
                            result_pages=[{"page_index": 1, "result_set_id": "L1", "viewports": [{"result_set_id": "L1",
                                "editor_value": query["rendered_query"], "rows": [{"documentId": "US D123456 S"}],
                                "screenshot_path": str(self.screenshot), "screenshot_sha256": image_hash}]}])
        self.receipt.update(provider=self.provider, operation="design_recall", right_type="design", query=self.entry["q"],
                            final_url=self.capture["final_url"],
                            plan_entry_sha256=canonical_digest(self.entry), query_semantics=query,
                            result_pages_sha256=canonical_digest(self.capture["result_pages"]), result_sha256=canonical_digest(self.capture["candidates"]))
        self.receipt["events"][0].update(rendered_query=query["rendered_query"], input_value=query["rendered_query"])
        self.receipt["events"].insert(1, {"action": "observe_query_binding", "actor": "agent", "at": now_iso(),
                                        "result_set_id": "L1", "query": query["rendered_query"], "total_hits": 1,
                                        "screenshot_path": str(self.screenshot), "screenshot_sha256": image_hash})
        self.receipt["events"][-1].update(result_set_id="L1", query_bound=True, screenshot_sha256=image_hash)
        self.write_receipt()
        self.validate()

    def test_strict_result_pages_and_history_remain_bound_after_rehashing(self):
        self.prepare_strict_ppubs_recall()
        self.capture["result_pages"][0]["viewports"][0]["editor_value"] = "different query"
        self.receipt["result_pages_sha256"] = canonical_digest(self.capture["result_pages"])
        self.write_receipt()
        with self.assertRaisesRegex(ValueError, "viewport query differs"):
            self.validate()

    def test_duplicate_row_coverage_is_recomputed_from_bound_pages_not_just_new_receipt_hashes(self):
        from record_browser_execution import ppubs_row_coverage
        from test_ppubs_row_counts import FIXTURE, coverage
        self.prepare_strict_ppubs_recall()
        self.capture["result_pages"] = deepcopy(FIXTURE["pages"])
        for page in self.capture["result_pages"]:
            page["result_set_id"] = "L1"
            for view in page["viewports"]:
                view.update(result_set_id="L1", editor_value=self.capture["query_semantics"]["rendered_query"],
                            screenshot_path=str(self.screenshot), screenshot_sha256=sha256_file(self.screenshot))
        self.capture["result_coverage"] = {**coverage(), "unretrieved_document_count": 0, "unretrieved_result_row_count": 0}
        self.capture["candidates"] = [{"record_number": record} for record in sorted({pair[1] for pair in
                                       self.capture["result_coverage"]["row_coverage"]["ordinal_records"]})]
        self.receipt["events"][1]["total_hits"] = 37
        def write_current():
            self.receipt.update(result_pages_sha256=canonical_digest(self.capture["result_pages"]),
                                result_coverage_sha256=canonical_digest(self.capture["result_coverage"]),
                                result_sha256=canonical_digest(self.capture["candidates"]))
            self.write_receipt()
        write_current()
        self.validate()
        pristine = deepcopy(self.capture)
        for mutation in ("proof", "missing", "unexpanded_family"):
            self.capture = deepcopy(pristine)
            if mutation == "proof":
                self.capture["result_coverage"]["row_coverage"]["ordinal_records"][0][1] = "USD999999S"
            elif mutation == "missing":
                for page in self.capture["result_pages"]:
                    for view in page["viewports"]:
                        view["rows"] = [row for row in view["rows"] if row["rowNumber"] != "4"]
                self.capture["result_coverage"]["row_coverage"] = ppubs_row_coverage(self.capture["result_pages"], 37)
                self.capture["result_coverage"].update(unretrieved_result_row_count=1, unretrieved_document_count=None)
            else:
                self.capture["result_coverage"]["unconfirmed_family_member_count"] = 1
            write_current()
            with self.assertRaisesRegex(ValueError, "PPS result-row coverage"):
                self.validate()

    def test_title_query_keeps_plan_submission_history_viewport_and_result_bindings(self):
        self.entry["filters"] = {"field": "title", "language": "en"}
        self.prepare_strict_ppubs_recall()
        self.assertEqual(self.capture["query_semantics"]["rendered_query"], "((lid AND strap).TI.) AND S.KD.")
        pristine_capture, pristine_receipt = deepcopy(self.capture), deepcopy(self.receipt)
        for mutation, error in (("plan_field", "receipt does not match"),
                                ("submission", "submitted query differs"),
                                ("history", "search history does not bind"),
                                ("viewport", "viewport query differs"),
                                ("results", "candidates differ from bound result pages")):
            with self.subTest(mutation=mutation):
                self.capture, self.receipt = deepcopy(pristine_capture), deepcopy(pristine_receipt)
                plan_entry = deepcopy(self.entry)
                if mutation == "plan_field":
                    plan_entry["filters"]["field"] = "structural_feature"
                elif mutation == "submission":
                    self.receipt["events"][0].update(rendered_query="lid AND strap", input_value="lid AND strap")
                elif mutation == "history":
                    self.receipt["events"][1]["query"] = "lid AND strap"
                elif mutation == "viewport":
                    self.capture["result_pages"][0]["viewports"][0]["editor_value"] = "lid AND strap"
                    self.receipt["result_pages_sha256"] = canonical_digest(self.capture["result_pages"])
                else:
                    self.capture["candidates"] = [{"record_number": "USD999999S"}]
                    self.receipt["result_sha256"] = canonical_digest(self.capture["candidates"])
                atomic_write_json(self.root / "search-plan.json", {"queries": {self.provider: [plan_entry]}})
                self.write_receipt()
                with self.assertRaisesRegex(ValueError, error):
                    self.validate()

    def test_recall_acceptance_uses_real_strict_capture_receipt_and_origin_gate(self):
        """Entirely synthetic temporary files; no mock gate or business fixture."""
        from run_browser_plan import completed_capture
        from verify_recall_acceptance import evaluate_recall
        self.prepare_strict_ppubs_recall()
        self.task["product"] = {"requested_asin": "B000000001"}
        plan = {"schema_version": self.task["schema_version"], "task_id": self.task["task_id"],
                "queries": {self.provider: [self.entry]}}
        self.capture["result_coverage"] = {"schema_valid": True, "total_hits": 1, "retrieved_hits": 1,
            "truncated": False, "completeness": "complete", "stop_reason": "all_results_retrieved"}
        self.receipt["result_coverage_sha256"] = canonical_digest(self.capture["result_coverage"])
        self.write_receipt()
        capture_path = self.root / "capture.json"
        run = {**self.entry, "run_id": "R1", "provider": self.provider, "status": "success",
               "plan_entry_sha256": canonical_digest(self.entry), "requirement_ids": []}
        record = {key: run[key] for key in ("provider", "query_id", "operation", "jurisdiction", "right_type",
                                          "plan_entry_sha256", "requirement_ids")}
        record.update(evidence_id="EV1", source_run_id="R1", payload={"candidates": deepcopy(self.capture["candidates"])})
        evidence = {"schema_version": self.task["schema_version"], "task_id": self.task["task_id"],
                    "source_runs": [run], "collections": {"patents": [record]}}
        candidates = {"schema_version": self.task["schema_version"], "task_id": self.task["task_id"], "patents": [
            {"candidate_id": "C1", "publication_number": "USD123456S", "right_type": "design", "evidence_refs": ["EV1"]}]}
        oracle = {"schema": "IPR-RECALL-ORACLE/1.0", "asin": "B000000001", "jurisdiction": "US", "right_type": "design",
            "expected_publication_numbers": ["USD123456S"], "identity_review": {"reviewer": "offline-test",
                "reasoning": "Synthetic identity fixture only, not live product evidence.", "artifacts": [
                    {"path": str(self.screenshot), "sha256": sha256_file(self.screenshot), "source_url": "https://example.test/synthetic"}]}}
        def persist():
            atomic_write_json(capture_path, self.capture)
            execution = {"query_id": self.entry["query_id"], "status": "success", "capture_path": str(capture_path),
                         "capture_sha256": sha256_file(capture_path), "plan_entry_sha256": canonical_digest(self.entry)}
            for name, value in (("task.json", self.task), ("search-plan.json", plan), ("evidence.json", evidence),
                                ("normalized-candidates.json", candidates), ("browser-execution-status.json",
                                {"task_id": self.task["task_id"], "queries": [execution]})):
                atomic_write_json(self.root / name, value)
            return execution
        pristine_capture, pristine_receipt = deepcopy(self.capture), deepcopy(self.receipt)
        execution = persist()
        self.assertNotIn("source_environment", run)
        self.assertNotIn("source_environment", self.capture)
        self.assertNotIn("source_environment", self.receipt)
        self.assertTrue(completed_capture(self.root, self.task, self.provider, self.entry, execution))
        self.assertEqual(evaluate_recall(self.root, oracle)["status"], "passed")
        for mutation in ("receipt_bytes", "rehash_wrong_query", "unofficial_host", "capture_test", "receipt_test", "run_test"):
            with self.subTest(mutation=mutation):
                self.capture, self.receipt = deepcopy(pristine_capture), deepcopy(pristine_receipt)
                run.pop("source_environment", None)
                if mutation == "unofficial_host":
                    self.capture["final_url"] = self.receipt["final_url"] = "https://example.test/not-uspto"
                elif mutation == "rehash_wrong_query":
                    self.receipt["events"][0].update(rendered_query="different query", input_value="different query")
                elif mutation.endswith("_test"):
                    {"capture_test": self.capture, "receipt_test": self.receipt, "run_test": run}[mutation]["source_environment"] = "test"
                self.write_receipt()
                execution = persist()
                if mutation == "receipt_bytes":
                    atomic_write_json(Path(self.capture["query_execution"]["path"]), {"changed": True})
                binding_valid = completed_capture(self.root, self.task, self.provider, self.entry, execution)
                self.assertEqual(binding_valid, mutation not in {"receipt_bytes", "rehash_wrong_query"})
                self.assertEqual(evaluate_recall(self.root, oracle)["status"], "incomplete")

    def test_strict_ppubs_compiler_shared_javascript_python_vectors(self):
        fixture = Path(__file__).resolve().parents[1] / "fixtures" / "ppubs-query-contract.json"
        task = {"schema_version": "2.4-free", "screening_revision": "recall-integrity-v1"}
        for item in json.loads(fixture.read_text())["cases"]:
            with self.subTest(query=item["q"], field=item["field"]):
                entry = {"q": item["q"], "strategy": item["strategy"], "right_type": item["right_type"],
                         "operation": item["right_type"] + "_recall", "jurisdiction": "US",
                         "filters": {"field": item["field"], "language": "en"}}
                if item.get("error"):
                    with self.assertRaisesRegex(ValueError, "UNSUPPORTED_QUERY_SEMANTICS"):
                        planned_browser_query("uspto_patent_browser", entry, task)
                else:
                    self.assertEqual(planned_browser_query("uspto_patent_browser", entry, task)["rendered_query"], item["rendered"])

    def test_title_query_task_context_matches_javascript_without_widening_legacy(self):
        task = {"schema_version": "2.4-free", "screening_revision": "recall-integrity-v1"}
        entry = {"q": "lid AND strap", "strategy": "boolean", "operation": "patent_recall",
                 "right_type": "patent", "jurisdiction": "US", "filters": {"field": "title", "language": "en"}}
        compiled = compile_ppubs_query(entry, "title")
        self.assertEqual(compiled["field_code"], "TI")
        self.assertEqual(planned_browser_query("uspto_patent_browser", entry, task), compiled)
        cases = [{"task": task, "entry": entry}, {"task": {}, "entry": entry},
                 {"task": {"schema_version": "2.4-free"}, "entry": entry}]
        for filters in ({"field": "title", "language": "ja"}, {"field": "TI", "language": "en"},
                        {"field": "locarno", "language": "en"}, {"field": "abstract", "language": "en"},
                        {"field": "title", "language": "en", "unexpected": True}):
            cases.append({"task": task, "entry": {**entry, "filters": filters}})
        cases.append({"task": task, "entry": {**entry, "q": "锅盖固定带"}})
        expected = []
        for item in cases:
            try:
                expected.append({"semantics": planned_browser_query("uspto_patent_browser", item["entry"], item["task"])})
            except ValueError as exc:
                self.assertIn("UNSUPPORTED_QUERY_SEMANTICS", str(exc))
                expected.append({"rejected": True})
        self.assertTrue(all(item == {"rejected": True} for item in expected[1:]))
        with self.assertRaisesRegex(ValueError, "unsupported owner/classification field"):
            planned_browser_query("uspto_patent_browser", entry)  # Reproduce the omitted-task call.
        js = """import {browserPlannedQuery} from './tools/cdp/cdp-cli.mjs';
let raw=''; for await (const chunk of process.stdin) raw+=chunk;
console.log(JSON.stringify(JSON.parse(raw).map(({task,entry})=>{
  try { return {semantics:browserPlannedQuery('uspto_patent_browser',entry,task)}; }
  catch(error) { if (!error.message.includes('UNSUPPORTED_QUERY_SEMANTICS')) throw error; return {rejected:true}; }
})));"""
        result = subprocess.run(["node", "--input-type=module", "-e", js],
            cwd=Path(__file__).resolve().parents[1], input=json.dumps(cases), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), expected)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.task = {"schema_version": "2.4-free", "task_id": "T1"}
        self.provider = "uspto_tmsearch_browser"
        self.entry = {"query_id": "Q1", "q": "TEST", "strategy": "exact", "operation": "trademark_recall",
                      "right_type": "trademark_word", "jurisdiction": "US"}
        (self.root / "search-plan.json").write_text(json.dumps({"queries": {self.provider: [self.entry]}}))
        self.screenshot = self.root / "screenshots" / "query.png"
        self.screenshot.parent.mkdir()
        self.screenshot.write_bytes(b"result-screenshot-fixture")
        self.capture = {"query_id": "Q1", "status": "success", "final_url": "https://tmsearch.uspto.gov/",
                        "screenshot_path": str(self.screenshot), "candidates": [{"serial_number": "12345678"}]}
        at = now_iso()
        self.capture["checked_at"] = at
        self.receipt = {"query_semantics": None, "result_coverage_sha256": canonical_digest({}), "media_coverage_sha256": canonical_digest({}), "task_id": "T1", "provider": self.provider, "query_id": "Q1", "operation": "trademark_recall",
                        "jurisdiction": "US", "right_type": "trademark_word", "query": "TEST",
                        "plan_entry_sha256": canonical_digest(self.entry), "mode": "automatic", "business_actions_by": "agent",
                        "outcome": "success", "final_url": self.capture["final_url"], "completed_at": at,
                        "result_sha256": canonical_digest(self.capture["candidates"]),
                        "events": [{"action": "submit_query", "actor": "agent", "at": at,
                                    "rendered_query": '"TEST"', "input_value": '"TEST"'},
                                   {"action": "observe_result", "actor": "agent", "at": at,
                                    "stable": True, "screenshot_sha256": hashlib.sha256(self.screenshot.read_bytes()).hexdigest()}]}
        self.write_receipt()

    def write_receipt(self):
        file = self.root / "raw" / "browser-execution" / "query.json"
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(self.receipt))
        self.capture["query_execution"] = {"path": str(file), "sha256": hashlib.sha256(file.read_bytes()).hexdigest()}

    def tearDown(self):
        self.temp.cleanup()

    def validate(self):
        return validate_browser_execution(self.capture, self.task, self.root, self.provider)

    def test_complete_receipt_and_legacy(self):
        self.assertIn("query_execution", self.validate())
        self.assertEqual(validate_browser_execution({}, {"schema_version": "2.3-free"}, self.root, self.provider), {})

    def test_rate_limit_original_page_identity_is_optional_but_digest_bound_when_present(self):
        self.capture.update(status="access_limited", error_code="BROWSER_RATE_LIMITED", candidates=[])
        self.receipt.update(outcome="access_limited", result_sha256=canonical_digest([]))
        self.write_receipt()
        self.validate()  # A historic capture without the optional field retains its receipt contract.
        page_ref = {"target_id": "A" * 32, "url": self.capture["final_url"]}
        self.capture["rate_limit_page"] = page_ref
        with self.assertRaisesRegex(ValueError, "receipt does not match"):
            self.validate()
        self.receipt["rate_limit_page_sha256"] = canonical_digest(page_ref)
        self.write_receipt()
        self.validate()
        self.capture["rate_limit_page"]["target_id"] = "B" * 32
        with self.assertRaisesRegex(ValueError, "receipt does not match"):
            self.validate()
        self.capture["rate_limit_page"]["url"] = "https://example.test/"
        with self.assertRaisesRegex(ValueError, "page identity"):
            self.validate()

    def test_headerless_tm_zero_is_bound_to_confirmed_submission_not_just_a_matching_input(self):
        self._headerless_tm_zero_case()

    def test_figurative_headerless_zero_accepts_empty_result_pages_with_confirmed_transition(self):
        self._headerless_tm_zero_case(figurative=True)

    def _headerless_tm_zero_case(self, figurative=False):
        self.entry.update(strategy="phrase", query_compiler_revision="tm-field-tags-v1")
        if figurative:
            self.entry.update(right_type="trademark_figurative", query_compiler_revision="tm-figurative-fields-v1",
                              filters={"field": "mark_description", "language": "en"}, derived_from=["product.mark_inventory[0]"])
        (self.root / "search-plan.json").write_text(json.dumps({"queries": {self.provider: [self.entry]}}))
        semantics = planned_browser_query(self.provider, self.entry, self.task)
        query = semantics["rendered_query"]
        baseline = {"url": "https://tmsearch.uspto.gov/", "zero_visible": False, "result_query": "", "card_count": 0}
        final_url = "https://tmsearch.uspto.gov/search/search-results"
        binding = {"query_bound": True, "input_value": query, "rendered_query": query, "search_mode": "Field tag and Search builder",
                   "total_hits": 0, "result_query": "", "loading": False, "parsed_count": 0, "result_view": "list",
                   "binding_method": "submitted_zero_transition_v1", "zero_result_transition": {
                       "submission_id": "attempt-1", "rendered_query": query, "baseline": baseline,
                       "method": "result_route", "final_url": final_url, "zero_visible": True, "observed_loading": False}}
        coverage = {"total_hits": 0, "retrieved_hits": 0, "pages_retrieved": 1}
        self.capture.update(status="no_result", candidates=[], final_url=final_url, query_binding=binding,
                            query_semantics=semantics, rendered_query=query, result_coverage=coverage, result_pages=[])
        self.receipt.update(outcome="no_result", result_sha256=canonical_digest([]), final_url=final_url,
                            query_semantics=semantics, plan_entry_sha256=canonical_digest(self.entry),
                            right_type=self.entry["right_type"], result_coverage_sha256=canonical_digest(coverage))
        self.receipt["events"][0].update(rendered_query=query, input_value=query, search_mode="Field tag and Search builder",
                                         submission_id="attempt-1", submission_confirmed=True, result_baseline=baseline)
        self.receipt["events"][-1].update(query_binding=binding, observed_count=0)
        self.write_receipt()
        self.validate()
        self.receipt["events"][0]["submission_id"] = "different-attempt"
        self.write_receipt()
        with self.assertRaisesRegex(ValueError, "confirmed transition"):
            self.validate()

    def test_patent_recall_uses_the_same_quoted_ppubs_phrase_as_the_executor(self):
        entry = {"q": "silicone lid strap with oval holes", "operation": "patent_recall",
                 "right_type": "patent", "filters": {"field": "structural_feature", "language": "en"}}
        self.assertEqual(planned_browser_query("uspto_patent_browser", entry), {
            "rendered_query": '"silicone lid strap with oval holes"',
            "strategy": "advanced_literal_phrase", "semantics": "advanced_literal_phrase",
            "requested_field": "structural_feature", "language_filter_applied": False,
        })
        with self.assertRaisesRegex(ValueError, "contains CJK"):
            planned_browser_query("uspto_patent_browser", {**entry, "q": "硅胶锅盖固定带"})

    def test_manual_attestation_and_static_flag_are_insufficient(self):
        self.capture["operator_attestation"] = {"confirmed": True}
        with self.assertRaisesRegex(ValueError, "MANUAL_BUSINESS_ACTION_FORBIDDEN"):
            self.validate()
        self.capture.pop("operator_attestation")
        self.capture.pop("query_execution")
        self.capture["automatic"] = True
        with self.assertRaisesRegex(ValueError, "AUTOMATIC_QUERY_EXECUTION_REQUIRED"):
            self.validate()

    def test_wrong_query_even_with_updated_receipt_hash_is_rejected(self):
        self.receipt["events"][0].update(rendered_query='"OTHER"', input_value='"OTHER"')
        self.write_receipt()
        with self.assertRaisesRegex(ValueError, "submitted query differs"):
            self.validate()

    def test_result_and_screenshot_tampering_are_rejected(self):
        self.capture["candidates"].append({"serial_number": "87654321"})
        with self.assertRaisesRegex(ValueError, "captured candidates differ"):
            self.validate()
        self.capture["candidates"].pop()
        self.screenshot.write_bytes(b"different query screenshot")
        with self.assertRaisesRegex(ValueError, "screenshot differs"):
            self.validate()

    def test_absent_execution_and_cross_country_are_rejected(self):
        self.receipt["events"] = self.receipt["events"][1:]
        self.write_receipt()
        with self.assertRaisesRegex(ValueError, "submission and result observation"):
            self.validate()
        self.receipt["jurisdiction"] = "JP"
        self.write_receipt()
        with self.assertRaisesRegex(ValueError, "receipt does not match"):
            self.validate()


if __name__ == "__main__":
    unittest.main()
