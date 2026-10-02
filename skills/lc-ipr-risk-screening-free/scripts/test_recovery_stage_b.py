"""08B source recovery stays bound to real request targets and original receipts."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common import atomic_write_json, load_json, sha256_bytes, sha256_json
from recovery_stage_b import (REVISION, dispatch_block, effective_result, effective_submission, project,
                              record_review, record_failure_closeout, recovery_state, request_identity)


class RecoveryStageBTests(unittest.TestCase):
    def setUp(self):
        self.task = {"task_id": "T08B", "continuous_recovery_revision": REVISION}
        self.provider = "epo_ops"
        self.row = {"query_id": "Q1", "operation": "patent_recall", "jurisdiction": "US",
                    "right_type": "patent", "q": "wheel", "range": "1-25", "page": 1}
        self.evidence = {"task_id": "T08B", "source_runs": []}
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.save()

    def save(self):
        atomic_write_json(self.path / "task.json", self.task)
        atomic_write_json(self.path / "evidence.json", self.evidence)

    def add_run(self, run_id="R1", *, status="failed", submission="submitted", **extra):
        run = {"run_id": run_id, "provider": self.provider, "operation": self.row["operation"],
               "jurisdiction": self.row["jurisdiction"], "right_type": self.row["right_type"],
               "query_id": self.row["query_id"], "plan_entry_sha256": sha256_json(self.row),
               "query": self.row["q"], "request_params": {"q": self.row["q"], "range": self.row["range"],
                   "page": self.row["page"], "right_type": self.row["right_type"]},
               "status": status, "submission_state": submission, "error_code": "TIMEOUT",
               "raw_paths": [], "detail": "request failed", **extra}
        self.evidence["source_runs"].append(run)
        self.save()
        return run

    def review(self, run, **extra):
        request = {"kind": "failure_review", "source_run_id": run["run_id"],
                   "source_run_sha256": sha256_json(run), "reviewer": "Reviewer",
                   "reasoning": "Original request and failure checked", "receipt_review": "original receipt checked",
                   "receipt_absence_reason": "no retained body; error receipt checked",
                   "material_review": "no valid material in this receipt", "remaining_work": "same target",
                   "failure_cause": "source timeout", "repair_basis": "source status recovered",
                   "source_rule_ref": "confirmed source policy", "source_allows_retry": True, **extra}
        event = record_review(self.path, request)
        self.evidence = load_json(self.path / "evidence.json")
        return event

    def unknown_check(self, run, outcome, **extra):
        request = {"kind": "unknown_check", "source_run_id": run["run_id"],
                   "source_run_sha256": sha256_json(run), "reviewer": "Reviewer",
                   "reasoning": "Original request checked", "original_receipt_review": "original timeout receipt",
                   "basis": "saved request status", "check_method": "existing_receipt",
                   "outcome": outcome, **extra}
        event = record_review(self.path, request)
        self.evidence = load_json(self.path / "evidence.json")
        return event

    def pre_submission_repair(self, run):
        event = record_review(self.path, {"kind": "pre_submission_repair",
            "source_run_id": run["run_id"], "source_run_sha256": sha256_json(run),
            "reviewer": "Reviewer", "reasoning": "Original non-submission and repair checked",
            "receipt_review": "original guard/error receipt checked", "failure_cause": "invalid input",
            "repair_basis": "input corrected", "condition_check": "current execution conditions revalidated"})
        self.evidence = load_json(self.path / "evidence.json")
        return event

    def test_legacy_is_unchanged_and_identity_ignores_action_name(self):
        self.assertIsNone(recovery_state({"task_id": "T08B"}, self.evidence, self.provider, self.row))
        changed = {**self.row, "query_id": "Q-RENAMED", "triage_action_id": "NEW", "candidate_id": "C-RENAMED"}
        self.assertEqual(request_identity(self.task, self.provider, self.row)["recovery_object_id"],
                         request_identity(self.task, self.provider, changed)["recovery_object_id"])
        changed["page"] = 2
        self.assertNotEqual(request_identity(self.task, self.provider, self.row)["recovery_object_id"],
                            request_identity(self.task, self.provider, changed)["recovery_object_id"])

    def test_failed_submission_needs_original_review_before_one_retry(self):
        first = self.add_run()
        self.assertEqual(recovery_state(self.task, self.evidence, self.provider, self.row)["state"], "awaiting_review")
        self.assertEqual(dispatch_block(self.task, self.evidence, self.provider, self.row),
                         "SOURCE_FAILURE_RECOVERY_REVIEW_REQUIRED")
        self.review(first)
        self.assertEqual(recovery_state(self.task, self.evidence, self.provider, self.row)["state"], "ready")
        self.add_run("R2")
        state = recovery_state(self.task, self.evidence, self.provider, {**self.row, "query_id": "Q-RENAMED"})
        self.assertEqual((state["state"], state["submitted_attempts"], state["remaining_automatic_retries"]),
                         ("blocked", 2, 0))

    def test_confirmed_non_submission_requires_repair_before_another_dispatch(self):
        from workflow_v24 import record_action_recovery
        first = self.add_run(submission="not_submitted", error_code="INPUT_INVALID")
        self.assertEqual(dispatch_block(self.task, self.evidence, self.provider, self.row),
                         "PRE_SUBMISSION_REPAIR_REVIEW_REQUIRED")
        self.pre_submission_repair(first)
        self.assertIsNone(dispatch_block(self.task, self.evidence, self.provider, self.row))
        self.assertEqual(recovery_state(self.task, self.evidence, self.provider, self.row)["submitted_attempts"], 0)
        with patch("workflow_v24.correction_enabled", return_value=True):
            self.assertEqual(record_action_recovery(self.path, self.provider, self.row)["reason"],
                             "confirmed_not_submitted_retry")
            with self.assertRaisesRegex(ValueError, "RECOVERY_RETRY_INTENTION_UNRESOLVED"):
                record_action_recovery(self.path, self.provider, self.row)

    def test_retry_intention_is_recorded_before_dispatch_and_cannot_be_reclaimed(self):
        from workflow_v24 import record_action_recovery
        self.task["workflow_correction_revision"] = "workflow-correction-v1"
        self.save()
        first = self.add_run()
        review = self.review(first)
        with patch("workflow_v24.correction_enabled", return_value=True):
            claim = record_action_recovery(self.path, self.provider, self.row)
        self.assertEqual((claim["reason"], claim["recovery_review_id"], claim["external_attempt_ordinal"]),
                         ("reviewed_submitted_failure_retry", review["review_id"], 2))
        with patch("workflow_v24.correction_enabled", return_value=True):
            with self.assertRaisesRegex(ValueError, "RECOVERY_RETRY_INTENTION_UNRESOLVED"):
                record_action_recovery(self.path, self.provider, self.row)

    def test_review_requires_source_rule_and_original_receipt(self):
        first = self.add_run()
        with self.assertRaisesRegex(ValueError, "RECOVERY_REVIEW_INCOMPLETE"):
            self.review(first, source_rule_ref="")
        with self.assertRaisesRegex(ValueError, "RECOVERY_ORIGINAL_RECEIPT_NOT_AUDITED"):
            self.review(first, receipt_absence_reason="")

    def test_partial_retained_positions_must_be_processed_before_retry(self):
        first = self.add_run(result_processing={"revision": "source-result-processing-v1"})
        with patch("source_result_processing.progress", return_value={"material_processing_complete": False}):
            with self.assertRaisesRegex(ValueError, "RECOVERY_RETAINED_PROCESSING_PENDING"):
                self.review(first)
        with patch("source_result_processing.progress", return_value={"material_processing_complete": True}):
            self.review(first)
        self.assertEqual(recovery_state(self.task, self.evidence, self.provider, self.row)["state"], "ready")

    def test_limit_and_zero_result_do_not_receive_technical_retry(self):
        self.add_run(error_code="RATE_LIMITED")
        self.assertEqual(recovery_state(self.task, self.evidence, self.provider, self.row)["state"], "awaiting_access")
        self.evidence["source_runs"] = []
        self.add_run(status="no_result", error_code="")
        self.assertEqual(recovery_state(self.task, self.evidence, self.provider, self.row)["state"], "result_available")

    def test_unknown_reserves_and_confirmed_not_submitted_does_not_spend_retry(self):
        first = self.add_run(submission="unknown")
        self.assertEqual(recovery_state(self.task, self.evidence, self.provider, self.row)["unknown_reserved_count"], 1)
        self.assertEqual(dispatch_block(self.task, self.evidence, self.provider, self.row),
                         "VERIFY_PRIOR_SUBMISSION_BEFORE_RETRY")
        self.unknown_check(first, "not_submitted")
        self.assertEqual(effective_submission(self.evidence, first), "not_submitted")
        self.assertEqual(recovery_state(self.task, self.evidence, self.provider, self.row)["submitted_attempts"], 0)
        self.assertEqual(dispatch_block(self.task, self.evidence, self.provider, self.row),
                         "PRE_SUBMISSION_REPAIR_REVIEW_REQUIRED")
        self.pre_submission_repair(first)
        self.assertIsNone(dispatch_block(self.task, self.evidence, self.provider, self.row))
        self.assertEqual(first["submission_state"], "unknown")

    def test_existing_exact_pre_source_guard_audit_stays_valid(self):
        first = self.add_run(submission="unknown", error_code="BROWSER_EXECUTION_FAILED",
            detail="SCENARIO_DISPATCH_INPUT_INVALID: current scenario/triage does not authorize this action")
        self.evidence["submission_state_reviews"] = [{"method": "pre_source_guard_audit",
            "source_run_id": first["run_id"], "source_run_sha256": sha256_json(first),
            "query_id": first["query_id"], "plan_entry_sha256": first["plan_entry_sha256"],
            "submission_state": "not_submitted", "reviewer": "Reviewer",
            "reasoning": "guard executed before source", "reviewed_at": "2026-09-25T00:00:00Z"}]
        self.assertEqual(effective_submission(self.evidence, first), "not_submitted")
        self.assertEqual(recovery_state(self.task, self.evidence, self.provider, self.row)["state"], "awaiting_review")
        self.save()
        self.pre_submission_repair(first)
        self.assertEqual(recovery_state(self.task, self.evidence, self.provider, self.row)["state"], "ready")

    def test_existing_epo_no_result_receipt_audit_is_not_a_retryable_failure(self):
        self.row["operation"] = "search"
        first = self.add_run(submission="unknown", status="access_limited", error_code="PROVIDER_HTTP_ERROR")
        self.evidence["submission_state_reviews"] = [{"method": "epo_search_receipt_audit",
            "source_run_id": first["run_id"], "source_run_sha256": sha256_json(first),
            "query_id": first["query_id"], "plan_entry_sha256": first["plan_entry_sha256"],
            "submission_state": "submitted", "result": "no_result", "reviewer": "Reviewer",
            "reasoning": "original EPO fault receipt confirmed no result", "reviewed_at": "2026-09-25T00:00:00Z"}]
        self.assertEqual((effective_submission(self.evidence, first), effective_result(self.evidence, first)),
                         ("submitted", "no_result"))
        self.assertEqual(recovery_state(self.task, self.evidence, self.provider, self.row)["state"], "result_available")
        self.assertEqual(dispatch_block(self.task, self.evidence, self.provider, self.row),
                         "RETAINED_RESULT_REVIEW_REQUIRED")
        self.save()
        with self.assertRaisesRegex(ValueError, "RECOVERY_NOT_UNRESOLVED_UNKNOWN"):
            self.unknown_check(first, "not_submitted")

    def test_status_query_audit_must_be_read_only(self):
        first = self.add_run(submission="unknown")
        with self.assertRaisesRegex(ValueError, "RECOVERY_STATUS_QUERY_NOT_READ_ONLY"):
            self.unknown_check(first, "submitted_running", check_method="qualified_status_query")
        self.unknown_check(first, "submitted_running", check_method="qualified_status_query",
                           query_is_read_only=True, source_rule_ref="source status endpoint rules")
        self.assertEqual(recovery_state(self.task, self.evidence, self.provider, self.row)["reason"],
                         "SOURCE_RESULT_PENDING")

    def test_submitted_running_is_not_success_or_failure(self):
        first = self.add_run(submission="unknown")
        self.unknown_check(first, "submitted_running")
        self.assertEqual(recovery_state(self.task, self.evidence, self.provider, self.row)["reason"],
                         "SOURCE_RESULT_PENDING")
        self.assertEqual(first["submission_state"], "unknown")

    def test_unknown_check_can_bind_obtained_result_to_original_request(self):
        first = self.add_run(submission="unknown")
        result = self.add_run("RESULT", status="success", submission="submitted", error_code="")
        self.unknown_check(first, "result_obtained", result_run_id=result["run_id"])
        state = recovery_state(self.task, self.evidence, self.provider, self.row)
        self.assertEqual(state["state"], "result_available")
        self.assertTrue(state["late_result_linked"])
        self.assertEqual(first["submission_state"], "unknown")

    def test_unknown_limited_requires_all_preconditions_and_never_releases_reservation(self):
        first = self.add_run(submission="unknown")
        with self.assertRaisesRegex(ValueError, "RECOVERY_UNKNOWN_LIMIT_PRECONDITIONS_REQUIRED"):
            self.unknown_check(first, "still_unknown", disposition="limited")
        with self.assertRaisesRegex(ValueError, "RECOVERY_UNKNOWN_LIMIT_BASIS_REQUIRED"):
            self.unknown_check(first, "still_unknown", disposition="limited", materials_reviewed=True,
                               actionable_work_done=True, no_check_route=True, no_recovery_dependency=True)
        self.unknown_check(first, "still_unknown", disposition="limited", materials_reviewed=True,
                           actionable_work_done=True, no_check_route=True, no_recovery_dependency=True,
                           materials_review_basis="retained response reviewed", actionable_work_basis="all ready actions processed",
                           no_check_route_basis="source has no status endpoint", no_recovery_dependency_basis="no pending access")
        state = recovery_state(self.task, self.evidence, self.provider, self.row)
        self.assertEqual((state["state"], state["unknown_reserved_count"]), ("blocked", 1))

    def test_late_result_links_original_without_second_attempt(self):
        first = self.add_run(submission="unknown")
        self.unknown_check(first, "still_unknown", disposition="limited", materials_reviewed=True,
                           actionable_work_done=True, no_check_route=True, no_recovery_dependency=True,
                           materials_review_basis="retained response reviewed", actionable_work_basis="all ready actions processed",
                           no_check_route_basis="source has no status endpoint", no_recovery_dependency_basis="no pending access")
        late = self.add_run("LATE", status="success", submission="submitted", error_code="")
        request = {"kind": "late_result_link", "source_run_id": first["run_id"],
                   "source_run_sha256": sha256_json(first), "result_run_id": late["run_id"],
                   "reviewer": "Reviewer", "reasoning": "Late response belongs to original request",
                   "match_basis": "same request target and provider response identifier"}
        record_review(self.path, request)
        self.evidence = load_json(self.path / "evidence.json")
        state = recovery_state(self.task, self.evidence, self.provider, self.row)
        self.assertEqual(state["state"], "result_available")
        self.assertTrue(state["late_result_linked"])
        self.assertEqual(dispatch_block(self.task, self.evidence, self.provider, self.row),
                         "RETAINED_RESULT_REVIEW_REQUIRED")
        view = project(self.task, {"status": "incomplete", "entries": [{"work_id": "SOURCE",
            "kind": "source_lookup", "state": "ready", "reason": "NECESSARY_ACTION_PENDING",
            "provider": self.provider, "query_id": self.row["query_id"]}]}, self.evidence,
            {"queries": {self.provider: [self.row]}})
        self.assertEqual((view["entries"][0]["state"], view["entries"][0]["reason"]),
                         ("awaiting_review", "RETAINED_RESULT_REVIEW_REQUIRED"))

    def test_late_result_cannot_be_linked_when_actual_request_target_is_unknown(self):
        first = self.add_run(submission="unknown", query="", request_params={})
        late = self.add_run("LATE", status="success", submission="submitted", error_code="",
                            query="", request_params={})
        with self.assertRaisesRegex(ValueError, "RECOVERY_LATE_RESULT_NOT_BOUND"):
            record_review(self.path, {"kind": "late_result_link", "source_run_id": first["run_id"],
                "source_run_sha256": sha256_json(first), "result_run_id": late["run_id"],
                "reviewer": "Reviewer", "reasoning": "check identity", "match_basis": "no target known"})

    def test_projection_keeps_one_queue_and_separate_material_work(self):
        self.add_run()
        view = {"status": "incomplete", "entries": [
            {"work_id": "S", "kind": "source_lookup", "state": "ready", "reason": "NECESSARY_ACTION_PENDING",
             "provider": self.provider, "query_id": self.row["query_id"]},
            {"work_id": "M", "kind": "agent_investigation", "state": "awaiting_review",
             "reason": "SOURCE_RESULTS_PENDING_PROCESSING"}]}
        result = project(self.task, view, self.evidence, {"queries": {self.provider: [self.row]}})
        self.assertEqual(len(result["entries"]), 2)
        self.assertEqual(result["entries"][0]["state"], "awaiting_review")
        self.assertEqual(result["entries"][1]["reason"], "SOURCE_RESULTS_PENDING_PROCESSING")

    def test_real_scenario_dispatch_and_next_work_share_gate(self):
        import test_scenario_planning as fixtures
        from workflow_v24 import scenario_dispatch_block_from_dir, work_view_from_dir
        fixture = fixtures.ScenarioPlanningTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        provider = "uspto_patent_browser"
        row = next(item for item in fixture.plan["queries"][provider]
                   if item["right_type"] == "patent")
        self.assertEqual(fixture.task["continuous_recovery_revision"], REVISION)
        run = {"run_id": "RUN-08B", "provider": provider, "operation": row["operation"],
               "query_id": row["query_id"], "plan_entry_sha256": sha256_json(row),
               "jurisdiction": row["jurisdiction"], "right_type": row["right_type"],
               "query": row["q"], "request_params": {"q": row["q"], "filters": row.get("filters"),
                   "strategy": row.get("strategy"), "right_type": row["right_type"]},
               "status": "failed", "submission_state": "submitted", "error_code": "BROWSER_SEMANTIC_TIMEOUT",
               "raw_paths": [], "detail": "source failed"}
        fixture.evidence["source_runs"] = [run]
        fixture.save()
        block = scenario_dispatch_block_from_dir(fixture.path, provider, row)
        self.assertEqual(block["code"], "SOURCE_FAILURE_RECOVERY_REVIEW_REQUIRED")
        view = work_view_from_dir(fixture.path)
        affected = [item for item in view["entries"] if item.get("query_id") == row["query_id"]]
        self.assertTrue(affected)
        self.assertTrue(all(item["state"] == "awaiting_review" for item in affected
                            if item["kind"] == "source_lookup"))

    def closeout_fixture(self, *, retained=True):
        from source_result_processing import REVISION as processing_revision, make_index
        self.task.update(retrieval_workflow_revision='api-first-v3', assessment_revision='known-findings-risk-v1',
                         presentation_policy_revision='operator-report-v1', result_processing_revision=processing_revision)
        self.save()
        extra = {'quota': {'network_request_attempted': True, 'used': 1}, 'error_code': 'HTTP_ERROR'}
        if retained:
            body = (b'<fault xmlns="http://ops.epo.org"><code>CLIENT.NotAcceptable</code>'
                    b'<message>Requested representation unavailable</message></fault>')
            path = self.path / 'fault.xml'
            path.write_bytes(body)
            coverage = {'schema_valid': False, 'retrieved_hits': 0}
            extra.update(evidence_type='patent', raw_paths=[path.name], payload_digest=sha256_bytes(body),
                metadata={'search_coverage': coverage}, result_processing=make_index(self.task,
                provider=self.provider, evidence_type='patent', status='failed', submission_state='submitted',
                raw_body=body, raw_suffix='xml', normalized={'candidates': []}, coverage=coverage,
                payload_digest=sha256_bytes(body)))
        run = self.add_run(**extra)
        review = {'reviewer': 'Reviewer', 'reasoning': 'Read retained failure and decide this round disposition',
                  'receipt_review': 'Read the original error response; no candidate records returned',
                  'material_review': 'No usable candidate content in this original error receipt',
                  'remaining_work': 'Keep exact fields unknown; review only when source route recovers',
                  'repair_basis': 'No protocol repair supported in the current authorized configuration',
                  'source_rule_ref': 'existing bounded request policy', 'source_allows_retry': False,
                  'retry_disposition': 'not_requested', 'no_retry_reason': 'Do not repeat unchanged rejected operation'}
        if not retained:
            review['receipt_absence_reason'] = 'Adapter retained no response body; existing error metadata read'
        kwargs = {'source_run_id': run['run_id'], 'source_run_sha256': sha256_json(run),
                  'receipt_disposition': {'outcome': 'non_result_error'} if retained else None,
                  'failure_review': review}
        return run, kwargs

    def test_failure_closeout_one_write_one_refresh_preserves_original_and_consumption(self):
        import recovery_stage_b as recovery
        import source_result_processing as processing
        run, request = self.closeout_fixture()
        before_task = (self.path / 'task.json').read_bytes()
        before_raw = (self.path / 'fault.xml').read_bytes()
        with patch.object(recovery, 'atomic_write_json', wraps=atomic_write_json) as writer, \
                patch.object(processing, 'progress', wraps=processing.progress) as refresh:
            result = record_failure_closeout(self.path, **request)
        writer.assert_called_once()
        refresh.assert_called_once()
        saved = load_json(self.path / 'evidence.json')
        self.assertEqual(saved['source_runs'], [run])
        self.assertEqual((self.path / 'task.json').read_bytes(), before_task)
        self.assertEqual((self.path / 'fault.xml').read_bytes(), before_raw)
        self.assertTrue(result['material_progress']['material_processing_complete'])
        self.assertTrue(result['recorded'])
        self.assertEqual(result['closeout']['source_facts']['quota'], run['quota'])
        self.assertEqual(result['closeout']['source_run_sha256'], sha256_json(run))
        self.assertEqual(result['closeout']['receipt_disposition_sha256'], sha256_json(saved['receipt_dispositions'][0]))
        self.assertEqual(result['closeout']['recovery_review_sha256'], sha256_json(saved['recovery_reviews'][0]))
        self.assertEqual(result['failure_review']['receipt_paths'], run['raw_paths'])
        self.assertIn(run['error_code'], result['failure_review']['failure_cause'])
        self.assertEqual(recovery_state(self.task, saved, self.provider, self.row)['remaining_automatic_retries'], 0)

    def test_failure_closeout_repeated_exact_input_reuses_original_child_receipts(self):
        import recovery_stage_b as recovery
        run, request = self.closeout_fixture()
        first = record_failure_closeout(self.path, **request)
        before = (self.path / 'evidence.json').read_bytes()
        with patch.object(recovery, 'atomic_write_json', wraps=atomic_write_json) as writer:
            second = record_failure_closeout(self.path, **request)
        writer.assert_not_called()
        self.assertFalse(second['recorded'])
        self.assertEqual(first['closeout'], second['closeout'])
        self.assertEqual(first['failure_review'], second['failure_review'])
        self.assertEqual(before, (self.path / 'evidence.json').read_bytes())

    def test_failure_closeout_bad_final_decision_rolls_back_receipt_classification(self):
        import recovery_stage_b as recovery
        _, request = self.closeout_fixture()
        request['failure_review'].pop('no_retry_reason')
        before = (self.path / 'evidence.json').read_bytes()
        with patch.object(recovery, 'atomic_write_json', wraps=atomic_write_json) as writer:
            with self.assertRaisesRegex(ValueError, 'RECOVERY_SOURCE_RETRY_NOT_ALLOWED'):
                record_failure_closeout(self.path, **request)
        writer.assert_not_called()
        self.assertEqual(before, (self.path / 'evidence.json').read_bytes())

    def test_failure_closeout_still_requires_real_material_and_recovery_judgments(self):
        _, request = self.closeout_fixture()
        before = (self.path / 'evidence.json').read_bytes()
        for missing in ('material_review', 'remaining_work', 'repair_basis', 'source_rule_ref', 'receipt_review'):
            with self.subTest(missing=missing):
                modified = {**request, 'failure_review': {k: v for k, v in request['failure_review'].items() if k != missing}}
                with self.assertRaises(ValueError):
                    record_failure_closeout(self.path, **modified)
                self.assertEqual(before, (self.path / 'evidence.json').read_bytes())

    def test_failure_closeout_rejects_policy_run_hash_and_child_identity_conflicts(self):
        run, request = self.closeout_fixture()
        before = (self.path / 'evidence.json').read_bytes()
        for update in ({'source_run_sha256': 'bad'},
                       {'failure_review': {**request['failure_review'], 'source_run_id': 'other'}},
                       {'failure_review': {**request['failure_review'], 'receipt_paths': ['other.xml']}},
                       {'receipt_disposition': {'outcome': 'non_result_error', 'source_run_sha256': 'bad'}}):
            with self.subTest(update=update):
                with self.assertRaises(ValueError):
                    record_failure_closeout(self.path, **{**request, **update})
                self.assertEqual(before, (self.path / 'evidence.json').read_bytes())
        self.task.pop('assessment_revision')
        self.save()
        with self.assertRaisesRegex(ValueError, 'NEW_POLICY_REQUIRED'):
            record_failure_closeout(self.path, **request)

    def test_failure_closeout_unknown_non_submission_and_zero_result_not_failure(self):
        run, request = self.closeout_fixture()
        for changes in ({'submission_state': 'unknown'}, {'submission_state': 'not_submitted'}, {'status': 'no_result'}, {'status': 'success'}):
            with self.subTest(changes=changes):
                changed = {**run, **changes}
                self.evidence['source_runs'] = [changed]
                self.save()
                before = (self.path / 'evidence.json').read_bytes()
                with self.assertRaisesRegex(ValueError, 'NOT_A_CONFIRMED_FAILURE'):
                    record_failure_closeout(self.path, **{**request, 'source_run_sha256': sha256_json(changed)})
                self.assertEqual(before, (self.path / 'evidence.json').read_bytes())

    def test_failure_closeout_original_tamper_is_not_auto_classified(self):
        _, request = self.closeout_fixture()
        (self.path / 'fault.xml').write_bytes(b'<fault>changed</fault>')
        before = (self.path / 'evidence.json').read_bytes()
        with self.assertRaises(ValueError):
            record_failure_closeout(self.path, **request)
        self.assertEqual(before, (self.path / 'evidence.json').read_bytes())

    def test_failure_closeout_no_body_requires_explicit_absence_review(self):
        import source_result_processing as processing
        _, request = self.closeout_fixture(retained=False)
        with patch.object(processing, 'progress', wraps=processing.progress) as refresh:
            result = record_failure_closeout(self.path, **request)
        refresh.assert_not_called()
        self.assertIsNone(result['receipt_disposition'])
        self.assertIsNone(result['material_progress'])
        self.assertTrue(result['failure_review']['receipt_absence_reason'])
        modified = {**request, 'failure_review': {k: v for k, v in request['failure_review'].items() if k != 'receipt_absence_reason'}}
        with self.assertRaisesRegex(ValueError, 'ORIGINAL_RECEIPT_NOT_AUDITED'):
            record_failure_closeout(self.path, **modified)

    def test_failure_closeout_cannot_hide_actual_unread_result_material(self):
        from source_result_processing import make_index
        import json
        run, request = self.closeout_fixture()
        body = json.dumps({'candidates': [{'publication_number': 'US1234567A1'}]}).encode()
        path = self.path / 'partial.json'
        path.write_bytes(body)
        coverage = {'schema_valid': True, 'retrieved_hits': 1}
        run.update(raw_paths=[path.name], payload_digest=sha256_bytes(body), metadata={'search_coverage': coverage},
            result_processing=make_index(self.task, provider=self.provider, evidence_type='patent', status='failed',
                submission_state='submitted', raw_body=body, raw_suffix='json', normalized={'candidates': []},
                coverage=coverage, payload_digest=sha256_bytes(body)))
        self.evidence['source_runs'] = [run]
        self.save()
        bound = {**request, 'source_run_sha256': sha256_json(run)}
        before = (self.path / 'evidence.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'RECEIPT_HAS_RESULT_MATERIAL'):
            record_failure_closeout(self.path, **bound)
        with self.assertRaisesRegex(ValueError, 'RETAINED_PROCESSING_PENDING'):
            record_failure_closeout(self.path, **{**bound, 'receipt_disposition': None})
        self.assertEqual(before, (self.path / 'evidence.json').read_bytes())

    def test_failure_closeout_detects_external_input_change_without_overwriting(self):
        import source_result_processing as processing
        _, request = self.closeout_fixture()
        original = processing.progress
        def changed(*args, **kwargs):
            result = original(*args, **kwargs)
            external = load_json(self.path / 'evidence.json')
            external['external_change'] = True
            atomic_write_json(self.path / 'evidence.json', external)
            return result
        with patch.object(processing, 'progress', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'INPUT_CHANGED'):
                record_failure_closeout(self.path, **request)
        saved = load_json(self.path / 'evidence.json')
        self.assertTrue(saved['external_change'])
        self.assertNotIn('receipt_dispositions', saved)
        self.assertNotIn('recovery_reviews', saved)

    def test_recovery_cli_dispatches_atomic_closeout_and_rejects_extra_fields(self):
        import io
        from contextlib import redirect_stdout
        import record_recovery_review as cli
        _, request = self.closeout_fixture()
        path = self.path / 'input.json'
        atomic_write_json(path, {'kind': 'failure_closeout', **request})
        argv = ['record_recovery_review', '--task-dir', str(self.path), '--input', str(path)]
        with patch('sys.argv', argv), redirect_stdout(io.StringIO()):
            cli.main()
        self.assertEqual(len(load_json(self.path / 'evidence.json')['failure_closeouts']), 1)
        atomic_write_json(path, {'kind': 'failure_closeout', **request, 'auto_review': True})
        with patch('sys.argv', argv), self.assertRaisesRegex(ValueError, 'INPUT_INVALID'):
            cli.main()


if __name__ == "__main__":
    unittest.main()
