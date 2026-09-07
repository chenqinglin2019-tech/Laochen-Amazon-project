"""Design-class routing is not a substitute for live recall acceptance."""
import unittest
from workflow_v24 import _applicable


class DesignClassScopeTests(unittest.TestCase):
    task = {"workflow_correction_revision": "workflow-correction-v1", "decision_workflow_revision": "scenario-triage-v1"}

    def test_design_uspc_only_routes_to_design_in_corrected_tasks(self):
        term = {"kind": "uspc", "value": "D8/394"}
        self.assertTrue(_applicable(term, "design", task=self.task))
        for right in ("patent", "utility_model"):
            self.assertFalse(_applicable(term, right, task=self.task))

    def test_ordinary_uspc_and_historical_plans_keep_existing_behavior(self):
        self.assertTrue(_applicable({"kind": "uspc", "value": "220/315"}, "patent", task=self.task))
        self.assertTrue(_applicable({"kind": "uspc", "value": "D8/394"}, "patent", task={}))
        self.assertTrue(_applicable({"kind": "cpc", "value": "B65D63/16"}, "patent", task=self.task))


if __name__ == "__main__":
    unittest.main()
