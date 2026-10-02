"""10B current-state classification never treats a tag or generated file as delivery."""
import copy
import unittest

from business_status_stage_b import REVISION, classify


class BusinessStatusTests(unittest.TestCase):
    def setUp(self):
        self.task = {"business_status_revision": REVISION}
        self.scope = {"scenario_id": "product_entry", "jurisdiction": "US", "right_type": "design",
            "product_version": "V1", "candidate_id": "D1"}
        self.judgment = {"event_id": "J1", "scope": self.scope, "applicability": "current",
            "review_status": "chief_reviewed", "stage_risk": "中"}
        self.stage = {"identity_errors": [], "product": {"product_version": "V1"},
            "progress": {"completed": 2, "planned": 2, "plan_version": 1},
            "progress_cutoff": {"source_run_count": 1}, "grade_cutoff": {"stage_review_event_count": 3},
            "stage_risk": {"overall": {"review_status": "complete", "applicability": "current"},
                "judgments": [self.judgment], "stage_review": {"batches": []}},
            "review_issues": [], "quarantined_judgments": []}
        self.view = {"entries": [], "unresolved_scopes": [], "active_pauses": [], "technical_stops": []}
        self.assessment = {"status": "completed"}

    def result(self, *, proof=None):
        return classify(self.task, self.stage, self.view, self.assessment,
            limitation_validator=(lambda entry: proof) if proof is not None else None)

    def blocked(self):
        self.stage["progress"].update(completed=1)
        self.stage["stage_risk"]["overall"]["review_status"] = "pending"
        self.assessment["status"] = "incomplete"
        self.view["entries"] = [{"work_id": "W1", "state": "blocked", "kind": "source_lookup",
            "reason": "NO_SUPPORTED_ROUTE", "scenario_id": "product_entry", "jurisdiction": "US",
            "right_type": "design", "query_id": "Q1", "impact": "当前设计判断的官方状态未核实",
            "resume_condition": "来源恢复后核实状态", "delivery_limit": {"kind": "source_constraint",
                "route_absence": {"kind": "no_qualified_route"}}}]
        self.view["unresolved_scopes"] = [{"scenario_id": "product_entry", "jurisdiction": "US",
            "right_type": "design"}]
        self.stage["stage_risk"]["stage_review"]["batches"] = [{"batch_id": "B1", "status": "complete",
            "scope": {key: self.scope[key] for key in ("scenario_id", "jurisdiction", "right_type", "product_version")},
            "coverage_notes": [{"subject": "limitations", "work_ids": ["W1"],
                "judgment_impact": "官方状态未核实，阶段结论保留限制"}]}]

    def test_business_completion_does_not_require_a_delivered_file(self):
        result = self.result()
        self.assertEqual(result["business_status"], "business_complete")
        self.assertEqual(result["delivery_status"], "not_verified")
        self.assertTrue(result["overall_business_complete"])

    def test_no_candidate_can_complete_when_all_obligations_are_closed(self):
        self.stage["stage_risk"]["judgments"] = []
        self.assertEqual(self.result()["business_status"], "business_complete")

    def test_missing_original_scope_cannot_close_limited_round(self):
        self.blocked()
        self.view["entries"][0].pop("scenario_id")
        result = self.result(proof=True)
        self.assertIn("ORIGINAL_OBLIGATION_SCOPE_MISSING", result["limitations"][0]["gaps"])

    def test_full_progress_with_unfinished_work_is_not_complete(self):
        self.view["entries"] = [{"work_id": "W1", "state": "ready", "kind": "agent_read"}]
        self.assertEqual(self.result()["business_status"], "continue")

    def test_true_limited_round_keeps_open_obligation(self):
        self.blocked()
        result = self.result(proof=True)
        self.assertEqual(result["business_status"], "limited_round_closed")
        self.assertFalse(result["overall_business_complete"])
        self.assertEqual(result["remaining_work_ids"], ["W1"])
        self.assertEqual(result["limitations"][0]["review_batch_id"], "B1")
        self.assertEqual(result["delivery_status"], "not_verified")

    def test_limit_tag_without_real_proof_or_review_cannot_close(self):
        self.blocked()
        self.stage["stage_risk"]["stage_review"]["batches"] = []
        result = self.result(proof=False)
        self.assertNotEqual(result["business_status"], "limited_round_closed")
        self.assertIn("LIMITATION_PROOF_UNVERIFIED", result["limitations"][0]["gaps"])
        self.assertIn("LIMITATION_09C_REVIEW_MISSING", result["limitations"][0]["gaps"])

    def test_attempt_receipt_alone_does_not_prove_no_alternative(self):
        self.blocked()
        self.view["entries"][0]["delivery_limit"]["source_run_refs"] = [{"run_id": "R1", "sha256": "abc"}]
        result = self.result(proof=True)
        self.assertNotEqual(result["business_status"], "limited_round_closed")
        self.assertIn("ALTERNATIVE_ROUTE_UNREVIEWED", result["limitations"][0]["gaps"])

    def test_unread_material_and_alternative_work_prevent_limited_closure(self):
        self.blocked()
        self.view["entries"][0].update(returned_count=3, reviewed_count=2)
        self.assertIn("RETAINED_MATERIAL_UNPROCESSED", self.result(proof=True)["limitations"][0]["gaps"])
        self.view["entries"][0].update(returned_count=3, reviewed_count=3)
        self.view["entries"].append({"work_id": "W2", "state": "ready", "kind": "source_lookup"})
        self.assertEqual(self.result(proof=True)["business_status"], "continue")

    def test_waiting_pause_and_technical_stop_do_not_close(self):
        self.view["entries"] = [{"work_id": "W1", "state": "awaiting_user"}]
        self.assertEqual(self.result()["business_status"], "awaiting_dependency")
        self.view["active_pauses"] = [{"scope": "task"}]
        self.assertEqual(self.result()["business_status"], "user_paused")
        self.view["active_pauses"] = []
        self.blocked()
        self.view["technical_stops"] = [{"work_id": "W1"}]
        self.assertNotEqual(self.result(proof=True)["business_status"], "limited_round_closed")

    def test_missing_impact_or_recovery_condition_is_not_evidence(self):
        self.blocked()
        self.view["entries"][0].pop("impact")
        self.stage["stage_risk"]["stage_review"]["batches"][0]["coverage_notes"][0].pop("judgment_impact")
        self.view["entries"][0].pop("resume_condition")
        gaps = self.result(proof=True)["limitations"][0]["gaps"]
        self.assertIn("JUDGMENT_IMPACT_UNREVIEWED", gaps)
        self.assertIn("RECOVERY_CONDITION_MISSING", gaps)

    def test_stale_identity_and_review_block_closure(self):
        self.stage["identity_errors"] = ["PRODUCT_VERSION_CHANGED"]
        self.assertEqual(self.result()["business_status"], "integrity_unavailable")
        self.stage["identity_errors"] = []
        self.stage["review_issues"] = ["INDEPENDENT_REVIEW_UNVERIFIED"]
        self.assertEqual(self.result()["business_status"], "review_pending")

    def test_same_work_id_multiple_affected_scopes_is_one_limitation(self):
        self.blocked()
        second = copy.deepcopy(self.view["entries"][0])
        second["candidate_id"] = "D2"
        self.view["entries"].append(second)
        result = self.result(proof=True)
        self.assertEqual(result["business_status"], "limited_round_closed")
        self.assertEqual(len(result["limitations"]), 1)
        self.assertEqual(len(result["limitations"][0]["affected_scopes"]), 2)

    def canonical_operator(self):
        self.blocked()
        self.task.update(assessment_revision='known-findings-risk-v1',
            presentation_policy_revision='operator-report-v1', review_policy_revision='final-double-review-v1')
        self.assessment['final_review'] = {'revision': 'final-double-review-v1', 'status': 'complete', 'evidence_digest': 'd' * 64}
        self.assessment['publication'] = {'mode': 'evidence', 'evidence_digest': 'd' * 64,
            'remaining_work': copy.deepcopy(self.view['entries']), 'limitations': copy.deepcopy(self.view['entries'])}
        self.stage['stage_risk']['stage_review']['batches'] = []

    def test_operator_accepted_publication_limit_closes_without_stage_reproof(self):
        self.canonical_operator()
        self.view['entries'][0].pop('resume_condition')
        result = self.result(proof=False)
        self.assertEqual(result['business_status'], 'limited_round_closed')
        self.assertEqual(result['closure_basis'], 'canonical_final_publication')
        self.assertFalse(result['overall_business_complete'])
        self.assertEqual(result['progress']['completed'], 1)
        self.assertIsNone(result['limitations'][0]['recovery_condition'])

    def test_operator_changed_work_or_review_cannot_reuse_publication_limit(self):
        for change in ('state', 'source', 'digest'):
            with self.subTest(change=change):
                self.setUp(); self.canonical_operator()
                if change == 'state': self.view['entries'][0]['state'] = 'submission_unknown'
                elif change == 'source': self.view['entries'][0]['source_run_refs'] = [{'run_id': 'NEW'}]
                else: self.assessment['publication']['evidence_digest'] = 'e' * 64
                self.assertNotEqual(self.result(proof=False)['business_status'], 'limited_round_closed')

    def test_operator_pause_and_missing_final_review_keep_round_open(self):
        self.canonical_operator()
        self.view['active_pauses'] = [{'scope': 'task'}]
        self.assertEqual(self.result(proof=False)['business_status'], 'user_paused')
        self.view['active_pauses'] = []
        self.assessment['final_review']['status'] = 'pending'
        self.assertNotEqual(self.result(proof=False)['business_status'], 'limited_round_closed')


if __name__ == "__main__":
    unittest.main()
