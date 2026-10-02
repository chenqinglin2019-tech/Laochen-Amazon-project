"""Batch input of record_discovery_semantics must equal sequential recording and stay atomic."""
import unittest

from common import atomic_write_json, load_json
from record_discovery_semantics import record, record_batch
from workflow_v24 import scenario_dispatch_block_from_dir
import test_discovery_semantics as fixtures


class DiscoverySemanticsBatchTests(unittest.TestCase):
    def fixture(self):
        helper = fixtures.DiscoverySemanticsTests("test_two_checks_gate_dispatch_and_complete_direction")
        helper.setUp()
        self.addCleanup(helper.doCleanups)
        helper.payloads = []
        helper.save = lambda payload: helper.payloads.append(payload)   # capture instead of recording
        return helper

    @staticmethod
    def stages(helper):
        return [(event["stage"], event.get("direction_id"), bool(event.get("review_sha256")))
                for event in load_json(helper.f.run / "task.json").get("discovery_semantic_reviews", [])]

    def test_batch_of_direction_and_before_reviews_matches_sequential_recording(self):
        sequential, batched = self.fixture(), self.fixture()
        sequential.direction(); sequential.before()
        for payload in sequential.payloads:
            atomic_write_json(sequential.input, payload)
            record(sequential.f.run, sequential.input)
        batched.direction(); batched.before()
        results = record_batch(batched.f.run, batched.payloads)
        self.assertEqual(len(results), 2)
        self.assertEqual(self.stages(sequential), self.stages(batched))
        self.assertIsNone(scenario_dispatch_block_from_dir(batched.f.run, batched.provider, batched.row))
        for event in results:
            self.assertTrue((batched.f.run / "raw" / "discovery_semantics" / (event["review_id"] + ".json")).is_file())
        # An identical request replayed inside a batch is idempotent, like a repeated single call.
        again = record_batch(batched.f.run, batched.payloads[:1])
        self.assertEqual(again[0]["review_id"], results[0]["review_id"])
        self.assertEqual(len(self.stages(batched)), 2)

    def test_a_failing_review_in_the_batch_writes_nothing(self):
        helper = self.fixture()
        helper.direction(); helper.before(query_id="NO-SUCH-QUERY")
        with self.assertRaises(ValueError):
            record_batch(helper.f.run, helper.payloads)
        self.assertEqual(self.stages(helper), [])
        self.assertFalse(list((helper.f.run / "raw").glob("discovery_semantics/*.json")) if (helper.f.run / "raw").exists() else [])

    def test_batch_after_result_review_follows_the_source_run(self):
        helper = self.fixture()
        helper.direction(); helper.before()
        record_batch(helper.f.run, helper.payloads)
        helper.source()
        helper.payloads.clear()
        helper.after()
        record_batch(helper.f.run, helper.payloads)
        self.assertEqual([stage for stage, _d, _h in self.stages(helper)], ["direction", "before", "after"])


if __name__ == "__main__":
    unittest.main()
