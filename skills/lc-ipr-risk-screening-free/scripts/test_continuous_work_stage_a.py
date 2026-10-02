"""08A issue/action identity and priority on the existing work view."""
import unittest

from continuous_work_stage_a import REVISION, project


class ContinuousWorkStageATests(unittest.TestCase):
    def setUp(self):
        self.task = {"task_id": "T-1", "continuous_work_stage_revision": REVISION}

    def test_legacy_task_is_unchanged(self):
        view = {"status": "incomplete", "entries": [{"work_id": "W"}]}
        self.assertIs(project({"task_id": "T-1"}, view), view)

    def test_submission_result_processing_and_obligation_stay_separate(self):
        view = {"status": "incomplete", "entries": [dict(work_id="W1", kind="agent_investigation",
            state="awaiting_review", reason="SOURCE_RESULTS_PENDING_PROCESSING", source_run_id="RUN1",
            pending_positions=[25, 26, 27, 28, 29, 30], returned_count=30, parsed_count=24,
            reviewed_count=24)]}
        evidence = {"source_runs": [{"run_id": "RUN1", "submission_state": "submitted", "status": "success"}]}
        row = project(self.task, view, evidence)["continuous_work"]["issues"][0]
        self.assertEqual(row["execution"][0], {"submission": "submitted", "result": "success"})
        self.assertEqual(row["material_processing"][0]["pending_positions"], [25, 26, 27, 28, 29, 30])
        self.assertEqual(row["obligation"], "open")

    def test_retained_result_processing_is_not_a_second_source_request(self):
        view = {"status": "incomplete", "entries": [
            dict(work_id="LOOKUP", kind="source_lookup", state="ready", query_id="Q1",
                 provider="registry", reason="NECESSARY_ACTION_PENDING"),
            dict(work_id="PROCESS", kind="agent_investigation", state="awaiting_review",
                 query_id="Q1", source_run_id="R1", provider="registry",
                 reason="SOURCE_RESULTS_PENDING_PROCESSING")]}
        result = project(self.task, view)
        ids = {row["work_id"]: row["linked_action_id"] for row in result["entries"]}
        self.assertNotEqual(ids["LOOKUP"], ids["PROCESS"])

    def test_issue_identity_survives_reason_and_state_change(self):
        base = dict(work_id="W1", kind="source_lookup", query_id="Q1", provider="registry",
            scenario_id="product_entry", jurisdiction="US", right_type="trademark_word",
            candidate_id="C1")
        first = project(self.task, {"status": "incomplete", "entries": [dict(base, state="ready", reason="NECESSARY_ACTION_PENDING")]})
        second = project(self.task, {"status": "incomplete", "entries": [dict(base, state="submission_unknown", reason="VERIFY_PRIOR_SUBMISSION_BEFORE_RETRY")]})
        self.assertEqual(first["entries"][0]["issue_id"], second["entries"][0]["issue_id"])
        self.assertEqual(first["entries"][0]["linked_action_id"], second["entries"][0]["linked_action_id"])

    def test_shared_query_is_one_action_for_two_scoped_issues(self):
        base = dict(kind="source_lookup", state="ready", provider="registry", query_id="Q-SHARED",
            evidence_obligation_id="OB-SHARED", scenario_id="product_entry", right_type="trademark_word")
        view = {"status": "incomplete", "entries": [dict(base, work_id="US", jurisdiction="US"),
            dict(base, work_id="GB", jurisdiction="GB")]}
        result = project(self.task, view)
        self.assertEqual(len(result["continuous_work"]["issues"]), 2)
        self.assertEqual(len(result["continuous_work"]["actions"]), 1)
        self.assertEqual(len(result["continuous_work"]["actions"][0]["issue_ids"]), 2)
        self.assertEqual([row["continuous_priority"]["basis"] for row in result["entries"]],
                         ["shared_action", "shared_action"])

    def test_two_actions_for_one_issue_do_not_close_it_on_one_receipt(self):
        base = dict(kind="source_lookup", state="ready", provider="registry",
                    evidence_obligation_id="VERIFY-STATUS", jurisdiction="US", right_type="patent",
                    candidate_id="C1")
        view = {"status": "incomplete", "entries": [
            dict(base, work_id="W1", query_id="Q1", source_run_refs=[{"run_id": "R1"}]),
            dict(base, work_id="W2", query_id="Q2")]}
        evidence = {"source_runs": [{"run_id": "R1", "submission_state": "submitted", "status": "success"}]}
        result = project(self.task, view, evidence)["continuous_work"]
        self.assertEqual(len(result["issues"]), 1)
        self.assertEqual(len(result["issues"][0]["action_ids"]), 2)
        self.assertEqual(len(result["issues"][0]["action_requirements"]), 2)
        self.assertEqual(result["issues"][0]["obligation"], "open")
        self.assertEqual({row["result"] for row in result["issues"][0]["execution"]},
                         {"success", "not_recorded"})

    def test_old_retained_work_precedes_new_source_and_waiting_remains(self):
        entries = [dict(work_id="NEW", kind="source_lookup", state="ready", query_id="Q2",
                        reason="NECESSARY_ACTION_PENDING", triage_priority={"received_order": 2}),
                   dict(work_id="OLD", kind="agent_investigation", state="awaiting_review",
                        source_run_id="R1", reason="SOURCE_RESULTS_PENDING_PROCESSING",
                        triage_priority={"received_order": 0}),
                   dict(work_id="WAIT", kind="source_lookup", state="awaiting_access", query_id="Q3",
                        reason="LOGIN_REQUIRED", triage_priority={"received_order": 0})]
        result = project(self.task, {"status": "incomplete", "entries": entries})
        self.assertEqual([row["work_id"] for row in result["entries"]], ["OLD", "NEW", "WAIT"])
        self.assertEqual(result["continuous_work"]["status"], "continue")
        self.assertEqual(len(result["entries"]), 3)

    def test_change_review_precedes_other_work_without_deleting_it(self):
        entries = [dict(work_id="A", kind="source_lookup", state="ready", query_id="Q1", reason="NECESSARY_ACTION_PENDING"),
                   dict(work_id="B", kind="agent_investigation", state="awaiting_review", change_event_id="CH1",
                        reason="M07_CHANGE_REVIEW_PENDING")]
        result = project(self.task, {"status": "incomplete", "entries": entries})
        self.assertEqual(result["entries"][0]["work_id"], "B")
        self.assertEqual(result["continuous_work"]["issues"][0]["obligation"], "open")

    def test_unknown_identity_remains_provisional(self):
        result = project(self.task, {"status": "incomplete", "entries": [
            dict(work_id="W-OLD", kind="agent_investigation", state="awaiting_review",
                 reason="IDENTITY_UNKNOWN", jurisdiction="US")]})
        issue = result["continuous_work"]["issues"][0]
        self.assertEqual(issue["identity_quality"], "provisional")
        self.assertNotIn("candidate_id", issue["scope"])

    def test_empty_work_is_only_ready_for_downstream_not_publication(self):
        result = project(self.task, {"status": "complete", "entries": []})
        self.assertEqual(result["continuous_work"]["status"], "stage_ready_for_downstream_review")

    def test_new_task_next_work_uses_same_queue_and_adds_issue_links(self):
        import test_scenario_planning as prior
        from workflow_v24 import work_view_from_dir
        fixture = prior.ScenarioPlanningTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        result = work_view_from_dir(fixture.path)
        self.assertEqual(result["continuous_work"]["revision"], REVISION)
        self.assertEqual(len(result["entries"]), sum(result["counts"].values()))
        self.assertTrue(all(row.get("issue_id") and row.get("linked_action_id") for row in result["entries"]))


if __name__ == "__main__":
    unittest.main()
