"""Regression tests for the continuous-work dispatcher projection."""
import unittest
from pathlib import Path
from unittest.mock import patch

from advance_work import actionable_packet, action_card, execute_sources, workflow_stage


class ContinuousWorkDispatchTests(unittest.TestCase):
    def test_source_lookup_triage_uses_retained_material_and_remains_pending(self):
        entry = {"work_id": "W-triage", "kind": "source_lookup", "state": "awaiting_review",
            "reason": "TRIAGE_REVIEW_REQUIRED", "provider": "serpapi_google_lens",
            "query_id": "Q-current", "scenario_id": "product_entry", "jurisdiction": "US",
            "right_type": "design", "source_run_refs": [{"run_id": "original", "sha256": "bound"}]}
        view = {"entries": [entry], "review_work": {"entries": []}}
        packet = actionable_packet(view)
        card = action_card(Path("/tmp/task"), packet["agent"][0])
        self.assertEqual(packet["source"], [])
        self.assertEqual(card["action"], "review_retained_discovery_candidates")
        self.assertEqual(card["work_id"], "W-triage")
        self.assertEqual(card["scope"]["query_id"], "Q-current")
        self.assertEqual(card["depends_on"], entry["source_run_refs"])
        self.assertTrue(card["merge_recorder"].endswith("merge_candidates.py"))
        self.assertTrue(card["identity_recorder"].endswith("record_candidate_identity_correction.py"))
        self.assertTrue(card["recorder"].endswith("annotate_materiality.py"))
        self.assertNotIn("command", card)
        with patch("advance_work.subprocess.run", side_effect=AssertionError("must not submit")):
            self.assertEqual(execute_sources(Path("/tmp/task"), {}, packet["source"]), [])
        self.assertEqual(actionable_packet(view)["agent"], [entry])

    def test_unknown_source_lookup_review_reason_still_rejected(self):
        with self.assertRaisesRegex(ValueError, "UNKNOWN_AGENT_WORK_KIND"):
            action_card(Path("/tmp/task"), {"kind": "source_lookup", "reason": "UNKNOWN_REASON"})

    def test_ready_serper_web_uses_api_runner_without_changing_review_dispatch(self):
        entry = {"kind": "source_lookup", "state": "ready", "query_id": "Q-web"}
        packet = actionable_packet({"entries": [entry]})
        completed = type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        with patch("advance_work.subprocess.run", return_value=completed) as run:
            results = execute_sources(Path("/tmp/task"), {"queries": {"serper_web": [{
                "query_id": "Q-web", "execution_phase": "discovery_initial"}]}}, packet["source"])
        self.assertEqual(results[0]["runner"], "api")
        self.assertEqual(results[0]["query_ids"], ["Q-web"])
        self.assertTrue(run.call_args.args[0][1].endswith("run_api_plan.py"))
        self.assertEqual(packet["agent"], [])

    def test_scope_review_is_an_action_card_and_blocks_completion(self):
        view = {"entries": [], "review_work": {"entries": [{
            "work_id": "WORK-review", "kind": "scope_review", "state": "awaiting_review",
            "scenario_id": "product_entry", "jurisdiction": "US", "right_type": "patent",
            "reason": "NECESSARY_SCOPE_REVIEW_REQUIRED"}]}}
        packet = actionable_packet(view)
        self.assertEqual([item["work_id"] for item in packet["review"]], ["WORK-review"])
        self.assertEqual(action_card(Path("/tmp/task"), packet["review"][0])["action"], "independent_scope_review")
        self.assertEqual(workflow_stage(view, packet, first_review=None, second_review=None,
                                        adjudication=None, output_dir=None), "independent_review")

    def test_current_progress_and_direction_work_have_action_cards(self):
        for reason, recorder in [('REVIEW_PROGRESS_QUERY_NOT_PLANNED', 'record_review_progress.py'),
                                 ('DISCOVERY_DIRECTION_REVIEW_REQUIRED', 'record_discovery_semantics.py')]:
            view = {'entries': [{'kind': 'agent_investigation', 'state': 'awaiting_review',
                                'reason': reason, 'query_id': 'Q-1', 'work_id': 'W-1'}]}
            packet = actionable_packet(view)
            card = action_card(Path('/tmp/task'), packet['agent'][0])
            self.assertTrue(card['recorder'].endswith(recorder))
            self.assertNotIn('command', card)
            self.assertEqual(packet['source'], [])

    def test_semantic_review_cards_preserve_scope_and_do_not_submit(self):
        for reason, stage in [("DISCOVERY_EXPRESSION_REVIEW_REQUIRED", "before"),
                              ("DISCOVERY_RESULT_SEMANTIC_REVIEW_REQUIRED", "after")]:
            entry = {"kind": "agent_investigation", "state": "awaiting_review", "reason": reason,
                     "query_id": "Q-current", "direction_id": "motor-patent", "work_id": "W-semantic",
                     "source_run_refs": [{"run_id": "original", "sha256": "retained"}]}
            packet = actionable_packet({"entries": [entry]})
            card = action_card(Path("/tmp/task"), packet["agent"][0])
            self.assertEqual(card["stage"], stage)
            self.assertEqual(card["scope"]["query_id"], "Q-current")
            self.assertEqual(card["depends_on"], entry["source_run_refs"])
            self.assertEqual(card["direction_id"], "motor-patent")
            self.assertTrue(card["recorder"].endswith("record_discovery_semantics.py"))
            self.assertNotIn("command", card)

    def test_professional_review_is_actionable_and_waiting_is_external_dependency(self):
        entry = {"kind": "professional_review", "state": "awaiting_review",
            "work_id": "W-prof", "action_id": "ACT-LINE", "candidate_id": "C1",
            "reason": "Resolve claimed line scope", "action": {
                "kind": "professional_review", "action_id": "ACT-LINE",
                "question": "Which linework is claimed?",
                "followup_basis": {"existing_evidence_refs": ["E1"]}}}
        packet = actionable_packet({"entries": [entry]})
        self.assertEqual(packet["agent"], [entry])
        card = action_card(Path("/tmp/task"), entry)
        self.assertEqual(card["action"], "obtain_external_professional_review")
        self.assertEqual(card["evidence_refs"], ["E1"])

        waiting = {**entry, "kind": "agent_investigation", "state": "awaiting_access",
                   "reason": "FOLLOWUP_WAITING", "dependency": "External opinion pending"}
        packet = actionable_packet({"entries": [waiting]})
        self.assertEqual(packet["waiting"], [waiting])

    def test_unknown_review_work_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "UNKNOWN_REVIEW_WORK_KIND"):
            actionable_packet({"entries": [], "review_work": {"entries": [{"kind": "surprise", "state": "ready"}]}})

    def test_unwritten_review_claim_cannot_advance_workflow(self):
        view = {"entries": [], "review_work": {"entries": []}}
        packet = actionable_packet(view)
        first, second, adjudication = Path("first.json"), Path("second.json"), Path("chief.json")
        self.assertEqual(workflow_stage(view, packet, first_review=first, second_review=second,
                                        adjudication=None, output_dir=None), "independent_review")
        self.assertEqual(workflow_stage(view, packet, first_review=first, second_review=second,
                                        adjudication=adjudication, output_dir=None), "independent_review")

    def test_external_limit_still_requires_written_reviews(self):
        view = {"entries": [{"work_id": "limited", "kind": "source_lookup", "state": "blocked"}],
                "review_work": {"entries": []}}
        packet = actionable_packet(view)
        self.assertEqual(workflow_stage(view, packet, first_review=Path("first.json"), second_review=Path("second.json"),
                                        adjudication=Path("chief.json"), output_dir=None), "independent_review")


class RetainedSourceReviewCardTests(unittest.TestCase):
    def test_specific_source_review_route_keeps_priority(self):
        entry={'kind':'source_lookup','state':'awaiting_review',
            'reason':'REVIEW_PROGRESS_QUERY_NOT_PLANNED','query_id':'Q1'}
        card=action_card(Path('/tmp/task'),entry)
        self.assertEqual(card['action'],'register_current_query_progress')
        self.assertTrue(card['recorder'].endswith('record_review_progress.py'))

    def test_minimal_source_review_card_is_representable_without_submission(self):
        from advance_work import action_card,actionable_packet,action_card_entries
        entry={'work_id':'EXACT-READ','kind':'source_lookup','state':'awaiting_review',
            'reason':'NECESSARY_CANDIDATE_EVIDENCE_MISSING','provider':'serpapi_google_patents','query_id':'Q1'}
        packet=actionable_packet({'entries':[entry]})
        cards=[action_card(Path('/tmp/task'),row) for row in action_card_entries(packet)]
        self.assertEqual(cards[0]['action'],'review_retained_source_obligation')
        self.assertNotIn('command',cards[0]);self.assertNotIn('completed',cards[0])
        self.assertEqual(cards[0]['reason'],entry['reason'])

if __name__ == "__main__":
    unittest.main()
