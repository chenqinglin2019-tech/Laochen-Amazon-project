"""Query counts depend on intact originals and reading, not completion flags."""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from common import atomic_write_json, load_json, sha256_json
from query_execution_progress import build
from review_progress_stage_a import _counts, _apply
from source_result_processing import append_dispositions
import test_source_result_processing as processing_fixture


class QueryExecutionProgressTests(unittest.TestCase):
    def setUp(self):
        fixture = processing_fixture.ResultProcessingTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.root = fixture.root
        self.run, self.evidence, _, _ = fixture.setup_run(count=2, parsed=2)
        self.task = {**fixture.task, "review_progress_revision": "review-progress-stage-a-v1",
                     "assessment_revision": "known-findings-risk-v1", "product_change_version": 1}
        self.query = {"query_id": self.run["query_id"], "q": "foam", "jurisdiction": "US",
                      "right_type": "patent", "operation": "search", "action_purpose": "discovery",
                      "discovery_scope": {"mode": "bounded", "max_pages": 1}}
        self.plan = {"queries": {self.run["provider"]: [self.query]}}
        self.run["plan_entry_sha256"] = sha256_json(self.query)
        self.item = {"item_id": "ITEM-1", "kind": "query", "provider": self.run["provider"],
                     "query_id": self.query["query_id"], "plan_entry_sha256": sha256_json(self.query),
                     "module_ids": ["06"], "scope": {"scenario_id": "product_entry", "jurisdiction": "US",
                       "right_type": "patent", "product_version": "1"}}
        self.saved_items = {}
        self.event("initialize", items=[self.item])
        self.save()

    def event(self, kind, **values):
        rows = self.evidence.setdefault("review_progress_events", [])
        event = {"event_id": "EV-" + str(len(rows)), "kind": kind, "version": len(rows)+1,
                 "prior_version": len(rows), "before": _counts(self.saved_items),
                 "reasoning": "unit fixture", **deepcopy(values)}
        _apply(self.saved_items, event)
        event["after"] = _counts(self.saved_items)
        rows.append(event)

    def save(self):
        atomic_write_json(self.root/"task.json", self.task)
        atomic_write_json(self.root/"evidence.json", self.evidence)

    def read(self):
        self.save()
        append_dispositions(self.root, self.run["run_id"], [
            {"position": i, "outcome": "non_candidate", "candidate_ids": [],
             "reviewer": "unit", "reason": "read full source row"} for i in (1, 2)])
        self.evidence = load_json(self.root/"evidence.json")
        self.run = self.evidence["source_runs"][0]

    def project(self, **options):
        return build(self.task, self.evidence, self.plan, task_dir=self.root, **options)

    def test_success_counts_only_after_reading_and_does_not_need_missing_acceptance_flag(self):
        before = self.project()
        self.assertEqual((before["completed_total"], before["planned_total"]), (0, 1))
        self.read()
        original = deepcopy(self.evidence)
        after = self.project()
        self.assertEqual((after["completed_total"], after["planned_total"], after["completion_percent"]), (1, 1, 100))
        self.assertEqual(after["formal_acceptance_ledger"]["completed"], 0)
        self.assertEqual(self.evidence, original)

    def test_original_tamper_revokes_even_recorded_completion(self):
        self.read()
        self.event("complete", item_id="ITEM-1", source_run_id=self.run["run_id"], evidence_refs=["EV-1"])
        (self.root/"source.json").write_text("changed source")
        result = self.project()
        self.assertEqual((result["completed_total"], result["planned_total"]), (0, 1))
        self.assertEqual(result["items"][0]["basis"], "SOURCE_ORIGINAL_INVALID")

    def test_failed_unknown_unsubmitted_and_unverified_zero_are_not_complete(self):
        self.read()
        for state, submission in [("failed", "submitted"), ("success", "unknown"),
                                  ("success", "not_submitted"), ("no_result", "submitted")]:
            with self.subTest(state=state, submission=submission):
                self.run.update(status=state, submission_state=submission)
                self.assertEqual(self.project()["completed_total"], 0)

    def test_retry_duplicate_items_and_shared_scopes_count_one_query(self):
        self.read()
        self.evidence["source_runs"].append({**deepcopy(self.run), "run_id": "old-failed", "status": "failed"})
        self.evidence["source_runs"].reverse()  # Current intact successful run last.
        duplicate = {**deepcopy(self.item), "item_id": "ITEM-2"}
        shared = {**deepcopy(self.item), "item_id": "ITEM-3", "scope": {**self.item["scope"], "scenario_id": "gift"}}
        self.event("add", items=[duplicate, shared])
        result = self.project()
        self.assertEqual((result["completed_total"], result["planned_total"]), (1, 1))
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(len(result["by_scope"]), 2)
        self.assertEqual(result["items"][0]["attempt_count"], 2)
        self.assertEqual(len(result["excluded_items"]), 1)

    def test_reopened_obligation_does_not_reuse_old_completion(self):
        self.read()
        self.event("complete", item_id="ITEM-1", source_run_id=self.run["run_id"], evidence_refs=["EV-1"])
        self.event("reopen", item_id="ITEM-1", upstream_ref="changed-fact")
        self.assertEqual(self.project()["completed_total"], 0)

    def test_changed_plan_does_not_count_historical_run_and_missing_registration_remains_pending(self):
        self.read()
        self.query["q"] = "different product clue"
        result = self.project(view={"entries": [{"query_id": self.query["query_id"], "kind": "source_lookup"}]})
        self.assertEqual((result["completed_total"], result["planned_total"]), (0, 1))
        self.assertEqual(result["items"][0]["basis"], "QUERY_NOT_REGISTERED_BEFORE_EXECUTION")

    def test_initial_hash_version_bridge_requires_unchanged_dependencies_and_real_change(self):
        self.read()
        target = "a"*64
        self.task["product_identity"] = {"sha256": target}
        self.item["scope"]["product_version"] = target
        self.evidence["review_progress_events"][0]["items"][0]["scope"]["product_version"] = target
        self.task["product_change_version"] = 2
        change = {"change_id": "CHG-1", "kind": "scope_change", "version": 2, "target_sha256": target,
                  "affected_query_ids": [], "affected_direction_ids": [], "affected_candidate_ids": [],
                  "expanded_candidate_ids": [], "fact_changes": [], "object_changes": []}
        change["sha256"] = sha256_json(change)
        self.task["product_change_history"] = [change]
        self.assertEqual(self.project()["completed_total"], 1)
        change["affected_query_ids"] = [self.query["query_id"]]
        change["sha256"] = sha256_json({k:v for k,v in change.items() if k != "sha256"})
        self.assertEqual(self.project()["completed_total"], 0)

    def test_empty_and_unregistered_plan_never_report_one_hundred_percent(self):
        self.evidence["review_progress_events"] = []
        unregistered = self.project()
        self.assertIsNone(unregistered["planned_total"])
        self.assertIsNone(unregistered["completion_percent"])
        self.saved_items = {}
        self.event("initialize", items=[])
        empty = self.project()
        self.assertEqual(empty["planned_total"], 0)
        self.assertIsNone(empty["completion_percent"])


if __name__ == "__main__":
    unittest.main()
