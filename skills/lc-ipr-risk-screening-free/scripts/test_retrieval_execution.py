import unittest
from retrieval_execution import selected_phase, in_phase


class RetrievalExecutionTests(unittest.TestCase):
    def test_legacy_defaults_preserved(self):
        self.assertEqual(selected_phase({}, "", "api"), "")
        self.assertTrue(in_phase({"execution_phase": "initial"}, ""))
        with self.assertRaisesRegex(ValueError, "REQUIRES_API_FIRST"):
            selected_phase({}, "discovery", "api")

    def test_defaults_and_transport_boundaries(self):
        task = {"retrieval_workflow_revision": "api-first-v1"}
        self.assertEqual(selected_phase(task, "", "api"), "discovery")
        self.assertEqual(selected_phase(task, "", "browser"), "verification")
        with self.assertRaisesRegex(ValueError, "INVALID"):
            selected_phase(task, "fallback", "api")
        with self.assertRaisesRegex(ValueError, "INVALID"):
            selected_phase(task, "discovery", "browser")

    def test_candidate_reads_and_fallback_are_separate(self):
        for phase in ("verification", "needs_info", "enrichment"):
            self.assertTrue(in_phase({"execution_phase": phase}, "verification"))
            self.assertFalse(in_phase({"execution_phase": phase}, "discovery"))
        self.assertTrue(in_phase({"execution_phase": "discovery_fallback"}, "fallback"))
        self.assertFalse(in_phase({"execution_phase": "discovery_fallback"}, "verification"))
        self.assertFalse(in_phase({"execution_phase": "initial"}, "fallback"))
