"""04C immutable execution consumption versus live identity statistics."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from common import atomic_write_json, load_json, sha256_json
from candidate_acquisition import REVISION, current_views, make_receipt, verified_receipt
from discovery_budget import snapshot, dispatch_block
import test_api_first_v2 as fixture


class CandidateAcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture.ApiFirstV2Tests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.task = self.fixture.task
        self.task["discovery_budget_revision"] = "discovery-purpose-budget-v1"
        self.fixture.regenerate()
        self.evidence = {"schema_version": self.task["schema_version"],
                         "task_id": self.task["task_id"], "source_runs": [], "collections": {}}
        self.task["candidate_acquisition_revision"] = REVISION
        self.provider = "uspto_patent_browser"
        self.browser = deepcopy(self.fixture.primary())
        self.browser.update(query_id="Q-04C", discovery_role="browser_fallback")
        self.plan = {"queries": {self.provider: [self.browser]}}

    def acquired(self, cards, *, positions=None):
        run_id = "RUN-" + str(len(self.evidence["source_runs"]))
        run = {"run_id": run_id, "provider": self.provider,
               "query_id": self.browser["query_id"],
               "plan_entry_sha256": sha256_json(self.browser),
               "status": "success", "submission_state": "submitted",
               "metadata": {"search_coverage": {"pages_retrieved": 1}},
               "evidence_type": "patent", "jurisdiction": "US", "payload_digest": "a" * 64}
        self.evidence["source_runs"].append(run)
        if positions is not None:
            run["result_processing"] = {"rows": [{"position": p} for p in positions]}
        receipt = make_receipt(self.task, self.evidence, run, self.browser,
                               {"candidates": cards})
        run["candidate_acquisition"] = receipt
        return run

    def test_exact_duplicates_consume_once_and_later_merge_does_not_refund(self):
        first = self.acquired([
            {"publication_number": "US11111111B2", "source_position": 1},
            {"publication_number": "US 11111111 B2", "source_position": 2},
            {"title": "incomplete A", "source_position": 3}], positions=[1, 2, 3])
        self.assertEqual(first["candidate_acquisition"]["new_unique_count"], 2)
        second = self.acquired([
            {"publication_number": "US11111111B2", "source_position": 1},
            {"title": "incomplete B", "source_position": 2}], positions=[1, 2])
        self.assertEqual(second["candidate_acquisition"]["new_unique_count"], 1)
        candidates = {"patents": [{"candidate_id": "CURRENT-1", "sources": [
            {"source_run_id": first["run_id"]}, {"source_run_id": second["run_id"]}]}]}
        state = snapshot(self.task, self.plan, self.evidence, self.browser, candidates=candidates)
        self.assertEqual(state["execution_consumed_count"], 3)
        self.assertEqual(state["current_candidate_count"], 1)
        self.assertEqual(state["remaining_browser_candidates"], 47)
        self.assertEqual(len(self.evidence["source_runs"]), 2)
        self.assertEqual(current_views(self.evidence, candidates)[0]["execution_consumed_count"], 3)
        self.assertEqual(current_views(self.evidence, candidates)[0]["current_candidate_count"], 1)

    def test_refined_browser_receipt_keeps_candidate_cap_and_version_identity(self):
        self.browser.update(discovery_role="refinement", refinement_round=1)
        run = self.acquired([{"publication_number": f"US{11111111+i}B2"} for i in range(50)])
        self.assertIsNotNone(verified_receipt(run))
        self.assertEqual(run["candidate_acquisition"]["version"], 1)
        self.assertEqual(snapshot(self.task, self.plan, self.evidence, self.browser)["execution_consumed_count"], 50)
        self.assertEqual(dispatch_block(self.task, self.plan, self.evidence, self.provider, self.browser),
                         "DISCOVERY_BROWSER_CANDIDATE_LIMIT")

    def test_all_57_acquired_cards_survive_and_stop_new_browser_acquisition(self):
        cards = [{"title": f"unconfirmed {i}", "source_position": i} for i in range(1, 58)]
        run = self.acquired(cards, positions=list(range(1, 58)))
        self.assertEqual(run["candidate_acquisition"]["new_unique_count"], 57)
        self.assertEqual(snapshot(self.task, self.plan, self.evidence, self.browser)["execution_consumed_count"], 57)
        self.assertEqual(dispatch_block(self.task, self.plan, self.evidence, self.provider, self.browser),
                         "DISCOVERY_BROWSER_CANDIDATE_LIMIT")
        self.assertEqual(len(run["candidate_acquisition"]["rows"]), 57)

    def test_unparsed_rows_keep_count_uncertain_and_retained_receipt_detects_change(self):
        run = self.acquired([{"title": "parsed", "source_position": 1}], positions=[1, 2, 3])
        state = snapshot(self.task, self.plan, self.evidence, self.browser)
        self.assertEqual(state["execution_consumed_count"], 1)
        self.assertEqual(len(state["unparsed_result_positions"]), 2)
        self.assertEqual(dispatch_block(self.task, self.plan, self.evidence, self.provider, self.browser),
                         "DISCOVERY_CANDIDATE_COUNT_PENDING_PARSE")
        changed = deepcopy(run)
        changed["candidate_acquisition"]["rows"][0]["identity_key"] = "forged"
        with self.assertRaisesRegex(ValueError, "RECEIPT_CHANGED"):
            verified_receipt(changed)

    def test_partial_unlocated_cards_do_not_claim_raw_positions_parsed(self):
        run = self.acquired([{"title": "card without stable source position"}], positions=[1, 2, 3])
        self.assertEqual(run["candidate_acquisition"]["unknown_positions"], [1, 2, 3])
        self.assertEqual(run["candidate_acquisition"]["new_unique_count"], 1)

    def test_real_record_result_freezes_count_on_one_source_run(self):
        from provider_utils import record_result
        provider = "synthetic_browser"
        plan = {"queries": {provider: [self.browser]}}
        task_dir = self.fixture.path
        atomic_write_json(task_dir / "task.json", self.task)
        atomic_write_json(task_dir / "search-plan.json", plan)
        atomic_write_json(task_dir / "evidence.json", self.evidence)
        cards = [{"publication_number": "US11111111B2"},
                 {"publication_number": "US 11111111 B2"}, {"title": "unfinished object"}]
        body = json.dumps({"candidates": cards}).encode()
        with patch("provider_utils.require_provider_operation", return_value=False):
            run = record_result(task_dir, provider=provider, operation="search",
                query="fixture", jurisdiction="US", evidence_type="patent", status="success",
                normalized={"candidates": cards, "search_metadata": {"schema_valid": True,
                    "retrieved_hits": 3}}, raw_body=body, raw_suffix="json", query_id=self.browser["query_id"],
                submission_state="submitted")
        saved = load_json(task_dir / "evidence.json")
        receipt = verified_receipt(saved["source_runs"][0])
        self.assertEqual(receipt["new_unique_count"], 2)
        self.assertEqual(len(saved["source_runs"]), 1)
        self.assertEqual(len(saved["collections"]["patents"][0]["payload"]["candidates"]), 3)
        self.assertEqual(run["result_processing"]["returned_count"], 3)

    def test_valid_failed_response_page_counts_but_unknown_submission_does_not(self):
        run = self.acquired([{"title": "readable card", "source_position": 1}], positions=[1])
        run["status"] = "failed"
        run["result_processing"].update(returned_count_basis="retained_rows", returned_count=1)
        run["metadata"]["search_coverage"]["schema_valid"] = True
        self.assertEqual(snapshot(self.task, self.plan, self.evidence, self.browser)["pages_acquired"], 1)
        run["submission_state"] = "unknown"
        self.assertEqual(snapshot(self.task, self.plan, self.evidence, self.browser)["pages_acquired"], 0)


if __name__ == "__main__":
    unittest.main()
