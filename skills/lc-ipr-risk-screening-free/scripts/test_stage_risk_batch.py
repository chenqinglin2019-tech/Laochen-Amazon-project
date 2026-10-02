"""record_events (09B batch) must equal sequential record_event calls and be atomic."""
import unittest

from common import load_json
from stage_risk_stage_b import record_event, record_events
import test_stage_risk_stage_b as fixtures


class StageRiskBatchTests(unittest.TestCase):
    def helper(self):
        helper = fixtures.StageRiskStageBTests("test_valid_supplement_closes_recursive_dependencies_in_risk_review_and_delivery")
        helper.setUp()
        self.addCleanup(helper.doCleanups)
        helper.save()
        return helper

    @staticmethod
    def shape(path):
        return [(e["kind"], e.get("scope", {}).get("candidate_id"), e.get("stage_risk"), e["version"],
                 bool(e["previous_event_id"])) for e in load_json(path / "evidence.json")["stage_risk_events"]]

    def requests(self, helper):
        return [helper.request(risk="高", candidate="C1", outcome="CMP1"),
                helper.request(risk="中", candidate="C2", outcome="CMP2")]

    def test_batch_equals_sequential_and_chains_previous_event_ids(self):
        sequential, batched = self.helper(), self.helper()
        for request in self.requests(sequential):
            sequential.record(request)
        events = record_events(batched.path, self.requests(batched))
        self.assertEqual(self.shape(sequential.path), self.shape(batched.path))
        stored = load_json(batched.path / "evidence.json")["stage_risk_events"]
        self.assertEqual(stored[1]["previous_event_id"], events[0]["event_id"])
        self.assertEqual([e["event_id"] for e in stored], [e["event_id"] for e in events])

    def test_one_invalid_event_leaves_the_evidence_untouched(self):
        helper = self.helper()
        bad = helper.request(risk="中", candidate="C2", outcome="CMP2", stage_risk="不存在的等级")
        with self.assertRaises(ValueError):
            record_events(helper.path, [helper.request(risk="高", candidate="C1", outcome="CMP1"), bad])
        self.assertEqual(load_json(helper.path / "evidence.json")["stage_risk_events"], [])
        with self.assertRaises(ValueError):
            record_events(helper.path, [])

    def test_batch_sees_earlier_events_of_the_same_batch_like_sequential_calls(self):
        sequential, batched = self.helper(), self.helper()
        first = sequential.request(risk="高", candidate="C1", outcome="CMP1")
        again = sequential.request(risk="中", candidate="C1", outcome="CMP1")   # same scope, no revision explanation
        sequential.record(first)
        with self.assertRaisesRegex(ValueError, "REVISION_EXPLANATION_REQUIRED"):
            sequential.record(again)
        # The batch applies the same rule to the second request because the first is already in memory.
        with self.assertRaisesRegex(ValueError, "REVISION_EXPLANATION_REQUIRED"):
            record_events(batched.path, [first, again])
        self.assertEqual(load_json(batched.path / "evidence.json")["stage_risk_events"], [])


if __name__ == "__main__":
    unittest.main()
