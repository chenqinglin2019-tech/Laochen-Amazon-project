"""Report-only partial delivery; synthetic local facts never invoke sources."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from common import sha256_json
from offline_test_support import isolated_test_environment
import necessary_completion as completion


class PartialPublicationTests(unittest.TestCase):
    def setUp(self):
        self.environment = isolated_test_environment()
        self.environment.__enter__()
        self.addCleanup(self.environment.__exit__, None, None, None)
        self.task = {"task_id": "OFFLINE-PARTIAL", "schema_version": "2.4-free",
            "assessment_policy": "evidence-estimate-v1", "assessment_revision": "partial-evidence-v1",
            "screening_revision": "recall-integrity-v1", "decision_workflow_revision": "scenario-triage-v1",
            "workflow_correction_revision": "workflow-correction-v1", "completion_policy_revision": "necessary-work-v2"}
        self.query = {"query_id": "Q", "operation": "patent_recall", "jurisdiction": "US", "right_type": "patent"}
        self.plan = {"queries": {"uspto_patent_browser": [self.query]}}
        self.run = {"run_id": "R", "query_id": "Q", "provider": "uspto_patent_browser",
            "plan_entry_sha256": sha256_json(self.query), "status": "failed",
            "error_code": "UNSUPPORTED_QUERY_SEMANTICS", "submission_state": "not_submitted"}
        self.evidence = {"source_runs": [self.run], "collections": {}}
        self.entry = {"work_id": "W", "query_id": "Q", "provider": "uspto_patent_browser",
            "scenario_id": "product_entry", "jurisdiction": "US", "right_type": "patent",
            "kind": "plan_repair", "state": "ready", "reason": "UNSUPPORTED_QUERY_SEMANTICS"}
        self.assessment = {"status": "incomplete", "coverage": {"scopes": []}, "assessments": [],
            "review": {"input_reviews": {"first": {}, "second": {}}}, "scenario_summaries": []}

    def proof(self):
        view = {"status": "incomplete", "entries": [self.entry], "counts": {"ready": 1},
            "unresolved_scopes": [{key: self.entry[key] for key in ("scenario_id", "jurisdiction", "right_type")}]}
        with patch("runtime_v24.resolved_capabilities", return_value={}), \
                patch("workflow_v24.resolved_work_view", return_value=view), \
                patch.object(completion, "review_work", return_value={"entries": [], "evidence_digest": "offline-digest"}):
            return completion.publication_context(self.task, self.evidence, {}, self.plan, {}, self.assessment, mode="auto")

    def test_recorded_internal_failure_is_reportable_without_changing_work_or_submission(self):
        before = deepcopy((self.task, self.evidence, self.plan, self.entry, self.assessment))
        proof = self.proof()
        self.assertEqual(proof["mode"], "evidence")
        self.assertEqual(proof["remaining_work"][0]["state"], "ready")
        self.assertEqual(proof["limitations"][0]["limitation_kind"], "internal_technical_failure")
        self.assertEqual(proof["limitations"][0]["failure_records"][0]["sha256"], sha256_json(self.run))
        self.assertEqual(before, (self.task, self.evidence, self.plan, self.entry, self.assessment))

    def test_bare_unexecuted_query_and_arbitrary_failure_cannot_use_exception(self):
        for change in ("missing", "wrong_hash", "unknown_submission", "later_success", "auth", "integrity"):
            with self.subTest(change=change):
                evidence, entry = deepcopy(self.evidence), deepcopy(self.entry)
                if change == "missing":
                    evidence["source_runs"] = []
                elif change == "wrong_hash":
                    evidence["source_runs"][0]["plan_entry_sha256"] = "wrong"
                elif change == "unknown_submission":
                    evidence["source_runs"][0]["submission_state"] = "unknown"
                elif change == "later_success":
                    evidence["source_runs"].append({**self.run, "run_id": "R2", "status": "success"})
                elif change == "auth":
                    evidence["source_runs"][0]["error_code"] = entry["reason"] = "AUTH_FAILED"
                else:
                    entry["integrity_failure"] = True
                self.assertIsNone(completion._partial_technical_limit(entry, evidence, self.plan, {}))

    def test_nonproduction_and_failed_material_cannot_use_exception(self):
        for metadata in ({"source_environment": "offline"}, {"environment": "fixture"},
                         {"fixture": True}, {"test_only": True}, {"metadata": {"kind": "mock"}}):
            with self.subTest(metadata=metadata):
                evidence = deepcopy(self.evidence)
                evidence["source_runs"][0].update(metadata)
                self.assertIsNone(completion._partial_technical_limit(self.entry, evidence, self.plan, {}))
        for payload in ({"candidates": [{"title": "Readable lead"}]},
                        {"documents": [{"path": "already-retained.pdf"}]},
                        {"response": {"full_text": "Available rights text"}}):
            with self.subTest(payload=payload):
                evidence = deepcopy(self.evidence)
                evidence["collections"] = {"discovery": [{"evidence_id": "E", "source_run_id": "R", "payload": payload}]}
                self.assertIsNone(completion._partial_technical_limit(self.entry, evidence, self.plan, {}))
                evidence["source_runs"].append({**self.run, "run_id": "R2"})
                self.assertIsNone(completion._partial_technical_limit(self.entry, evidence, self.plan, {}))
                evidence["source_runs"][0]["status"] = "success"
                self.assertIsNone(completion._partial_technical_limit(self.entry, evidence, self.plan, {}))

    def test_browser_pre_submission_failure_requires_retained_verified_capture(self):
        from common import atomic_write_json, sha256_file
        current = {key: value for key, value in self.run.items() if key != "run_id"}
        snapshots = {"browser-execution-status.json": {"queries": [current]}}
        self.assertIsNone(completion._partial_technical_limit(self.entry, {"source_runs": []}, self.plan, snapshots))
        with tempfile.TemporaryDirectory(prefix="ipr-retained-failure-") as tmp:
            path = Path(tmp) / "capture.json"
            atomic_write_json(path, current)
            current.update(capture_path=str(path), capture_sha256=sha256_file(path))
            proof = completion._partial_technical_limit(self.entry, {"source_runs": []}, self.plan, snapshots, task_dir=tmp)
            self.assertEqual(proof["failure_records"], [{"kind": "browser_execution_record",
                "sha256": sha256_json(current), "capture_sha256": sha256_file(path)}])
            for mutation in ({"plan_entry_sha256": "wrong"}, {"capture_sha256": "wrong"},
                             {"capture_path": "missing.json"}):
                with self.subTest(mutation=mutation), patch.dict(current, mutation):
                    self.assertIsNone(completion._partial_technical_limit(self.entry, {"source_runs": []}, self.plan, snapshots, task_dir=tmp))
            atomic_write_json(path, {**self.run, "payload": {"candidates": [{"title": "Unread"}]}})
            current["capture_sha256"] = sha256_file(path)
            self.assertIsNone(completion._partial_technical_limit(self.entry, {"source_runs": []}, self.plan, snapshots, task_dir=tmp))

    def test_unread_work_and_historical_policy_are_not_exempted(self):
        for kind, state in (("agent_read", "awaiting_review"), ("triage", "awaiting_review"),
                            ("agent_investigation", "ready"), ("source_lookup", "submission_unknown")):
            with self.subTest(kind=kind, state=state), patch.dict(self.entry, {"kind": kind, "state": state}):
                with self.assertRaisesRegex(ValueError, "EVIDENCE_AGENT_WORK_REMAINS"):
                    self.proof()
        self.task.pop("assessment_revision")
        with self.assertRaisesRegex(ValueError, "EVIDENCE_AGENT_WORK_REMAINS"):
            self.proof()


class PartialReassessmentIntegrationTests(unittest.TestCase):
    def test_retained_failed_searches_publish_new_low_report_without_touching_source(self):
        from common import atomic_write_json, load_json, sha256_file
        from assessment_estimate import review_digest
        from publish_report import publish
        from report_estimate import validate_run
        from test_evidence_delivery_integration import build_evidence_delivery_fixture
        with isolated_test_environment(), tempfile.TemporaryDirectory(prefix="ipr-partial-report-") as tmp:
            root = Path(tmp)
            fixture = build_evidence_delivery_fixture(root / "source", scenario="all_discovery_failed")
            source = Path(fixture["directory"])
            baseline = {str(path): sha256_file(path) for path in source.rglob("*") if path.is_file()}
            task = load_json(source / "task.json")
            self.assertNotIn("assessment_revision", task)
            task["assessment_revision"] = "partial-evidence-v1"
            evidence = load_json(source / "evidence.json")
            candidates = load_json(source / "normalized-candidates.json")
            ledger = load_json(source / "materiality-annotations.json")
            plan = load_json(source / "search-plan.json")
            digest = review_digest(evidence, candidates, ledger, plan, task)
            paths = []
            for name in ("first-review.json", "second-review.json"):
                review = load_json(source / name)
                review["review_context"]["evidence_digest"] = digest
                path = root / name
                atomic_write_json(path, review)
                paths.append(path)
            output = root / "new-report"
            result = publish(source, *paths, output_dir=output, assessment_revision="partial-evidence-v1")
            data = load_json(output / "report-data.json")
            self.assertEqual((data["overall"]["risk"], data["overall"]["confidence"]), ("低", "低"))
            self.assertEqual(result["business_completion"], "incomplete")
            self.assertEqual(result["delivery_status"], "completed")
            self.assertEqual(validate_run(source, load_json(output / "task.json"), output_dir=output), [])
            self.assertIn("有效检索为零", (output / "report.html").read_text(encoding="utf-8"))
            self.assertEqual(baseline, {str(path): sha256_file(path) for path in source.rglob("*") if path.is_file()})


class PartialExecutionIsolationTests(unittest.TestCase):
    def test_rating_revision_does_not_change_api_plan_or_dispatch_decisions(self):
        import test_api_first_planning as fixtures
        from workflow_v24 import scenario_dispatch_block_from_dir
        with isolated_test_environment():
            fixture = fixtures.ApiFirstPlanningTests()
            fixture.setUp()
            try:
                original = deepcopy(fixture.plan)
                before = {(provider, query["query_id"]): scenario_dispatch_block_from_dir(fixture.path, provider, query)
                    for provider, queries in original["queries"].items() for query in queries}
                fixture.task["assessment_revision"] = "partial-evidence-v1"
                changed = fixture.regenerate()
                self.assertEqual(original["queries"], changed["queries"])
                self.assertEqual(original.get("planning_gaps"), changed.get("planning_gaps"))
                after = {(provider, query["query_id"]): scenario_dispatch_block_from_dir(fixture.path, provider, query)
                    for provider, queries in changed["queries"].items() for query in queries}
                self.assertEqual(before, after)
            finally:
                fixture.tearDown()


if __name__ == "__main__":
    unittest.main()
