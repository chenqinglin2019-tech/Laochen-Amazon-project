"""Snapshot memo changes computation cost, never business evidence or semantics."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch

import decision_workflow as workflow
import test_scenario_planning
import test_historical_evidence
import historical_evidence


class DecisionSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.f = test_scenario_planning.ScenarioPlanningTests()
        self.f.setUp()
        self.addCleanup(self.f.tearDown)
        self.f.annotate()

    def snapshot(self):
        f = self.f
        return workflow.decision_snapshot(f.task, f.evidence, f.candidates, f.plan, f.ledger)

    def decision(self):
        f = self.f
        return workflow.effective_decision(f.task, f.ledger, "trademarks", f.candidate,
            "product_entry", "US", evidence=f.evidence)

    def test_identical_semantics_one_computation_and_caller_cannot_poison_memo(self):
        expected = self.decision()
        with patch.object(workflow, "_effective_decision", wraps=workflow._effective_decision) as calculate:
            with self.snapshot() as context:
                first = self.decision()
                first["decision"] = "not_selected"
                first["annotation"]["reason"] = "caller changed returned copy"
                self.assertEqual(self.decision(), expected)
                self.assertEqual(calculate.call_count, 1)
                self.assertGreater(context["hits"], 0)
            self.assertEqual(context["memo"], {})
            self.assertEqual(context["retained"], {})
            self.assertEqual(self.decision(), expected)
            self.assertEqual(calculate.call_count, 2)

    def test_in_place_input_change_rejected_and_new_call_reopens(self):
        with self.assertRaisesRegex(ValueError, "DECISION_SNAPSHOT_INPUT_MUTATED"):
            with self.snapshot():
                self.decision()
                self.f.candidate["goods_services"] = ["different protected goods"]
                self.decision()
        self.assertEqual(self.decision()["decision"], "unreviewed")
        with self.snapshot():
            self.assertEqual(self.decision()["decision"], "unreviewed")

    def test_exception_clears_context_and_next_scope_cannot_reuse_it(self):
        with self.assertRaisesRegex(RuntimeError, "fixture"):
            with self.snapshot() as old:
                self.decision()
                raise RuntimeError("fixture")
        self.assertIsNone(workflow._SNAPSHOT.get())
        with self.snapshot() as new:
            self.assertIsNot(old, new)
            self.assertEqual(new["memo"], {})

    def test_nested_same_context_shares_and_other_context_restores(self):
        with self.snapshot() as outer:
            with self.snapshot() as inner:
                self.assertIs(inner, outer)
            f = self.f
            with workflow.decision_snapshot(deepcopy(f.task), f.evidence, f.candidates, f.plan, f.ledger) as other:
                self.assertIsNot(other, outer)
            self.assertIs(workflow._SNAPSHOT.get(), outer)

    def test_no_context_leaks_to_parallel_worker(self):
        with self.snapshot():
            self.decision()
            with ThreadPoolExecutor(max_workers=1) as pool:
                self.assertIsNone(pool.submit(workflow._SNAPSHOT.get).result())

    def test_changed_unrelated_content_does_not_reopen_existing_candidate(self):
        expected = self.decision()
        with self.snapshot():
            self.assertEqual(self.decision(), expected)
        self.f.evidence["collections"]["unrelated"] = [{"evidence_id": "UNRELATED", "payload": {"title": "other record"}}]
        with self.snapshot():
            self.assertEqual(self.decision(), expected)


class HistoricalSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.f = test_historical_evidence.HistoricalEvidenceTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def test_unrelated_scope_does_not_read_files_but_exact_match_still_validates(self):
        f = self.f
        other = deepcopy(f.row)
        other["action_purpose"] = "needs_info:only abstract"
        with patch("assessment_estimate.validate_supplement") as validate:
            self.assertIsNone(historical_evidence.historical_action_reuse(
                f.task, f.provider, other, f.candidates, f.supplement, f.root))
            validate.assert_not_called()
        self.assertIsNotNone(f.reuse())

    def test_source_file_tamper_is_rechecked_even_inside_same_snapshot(self):
        f = self.f
        with workflow.decision_snapshot(f.task, {}, f.candidates, {}, {}, f.supplement):
            self.assertIsNotNone(f.reuse())
            (f.old / "response.json").write_bytes(b"changed exact source")
            self.assertIsNone(f.reuse())


if __name__ == "__main__":
    unittest.main()
