"""07D scoped gaps, batch accounting, change review and completion."""
import unittest

import test_distinctive_rights_review as prior


class StageDTests(unittest.TestCase):
    def setUp(self):
        self.previous = prior.ReviewTests()
        self.previous.setUp()
        self.fx = self.previous.fx
        self.addCleanup(self.fx.tmp.cleanup)

    def test_structural_gap_no_longer_asks_user_and_unread_material_stays_work(self):
        from unittest.mock import patch
        from distinctive_rights_stage_d import project_stage_d
        from distinctive_rights import work_entries
        request = {'request_id':'PF-STRUCT'}
        gap = {'kind':'gap', 'event_id':'G-STRUCT', 'gap_id':'G1', 'action_kind':'user_fact',
               'product_feedback_request_id':'PF-STRUCT'}
        follow = {'kind':'followup', 'event_id':'FOLLOW', 'gap_event_id':'G-STRUCT', 'outcome':'waiting'}
        limit = {'kind':'product_information_limit', 'state':'blocked',
                 'reason':'PRODUCT_STRUCTURE_UNAVAILABLE', 'question':'',
                 'delivery_limit':{'kind':'product_structure_unavailable'}}
        with patch('product_feedback.unavailable', return_value=[request]), \
             patch('product_feedback.structure_limitation_entry', return_value=limit):
            view = project_stage_d({}, {}, [gap, follow], {},
                [{'reason':'M07_MATERIAL_UNREAD', 'material_event_id':'M1'}])
        scope = {'candidate_id':'C1', 'scenario_id':'product_entry', 'jurisdiction':'US',
                 'right_type':'trade_dress', **view}
        entries = work_entries({'scopes':[scope]})
        structural = next(row for row in entries if row['reason'] == 'PRODUCT_STRUCTURE_UNAVAILABLE')
        self.assertEqual((structural['state'], structural['question']), ('blocked', ''))
        unread = next(row for row in entries if row['reason'] == 'M07_MATERIAL_UNREAD')
        self.assertEqual(unread['state'], 'awaiting_review')
        self.assertEqual(view['status'], 'in_progress')

    def ready(self):
        materials, facts = self.previous.trademark()
        comparison = self.previous.compare(materials, facts)
        self.fx.add("enforcement_scope", needed=False,
            reasoning="No public-enforcement investigation is necessary for this bounded scope",
            planned_query_ids=[], evidence_refs=["E1"])
        return materials, facts, comparison

    def batch(self, materials, *, processed=None, **changes):
        values = dict(batch_id="import:E1", received_evidence_refs=["E1"],
            disposition_by_evidence_ref={"E1": "Reviewed actual retained source for this scope"},
            received_material_event_ids=materials,
            processed_material_event_ids=materials if processed is None else processed,
            unread_disposition_reasons={}, disposition_reasoning="All relevant source material accounted")
        values.update(changes)
        return self.fx.add("batch", **values)

    def gap(self, **changes):
        values = dict(gap_id="G-1", question="Which specific use is permitted?",
            affected_judgment="Actual mark use", affected_reason_codes=["M07_GAP_OPEN"],
            affected_event_ids=[], existing_material_check="Read retained source page and context",
            minimum_action="Read the single relevant clause", completion_condition="Clause assessed for this use",
            action_kind="read_existing", evidence_refs=["E1"])
        values.update(changes)
        return self.fx.add("gap", **values)

    def follow(self, gap, outcome="waiting", **changes):
        values = dict(gap_id=gap["gap_id"], gap_event_id=gap["event_id"],
            action_id="A-SHARED", outcome=outcome, result_review="Read and classified actual result",
            remaining_impact="The permitted use remains unknown", evidence_refs=["E1"],
            next_action_or_dependency="Wait for the necessary source")
        values.update(changes)
        return self.fx.add("followup", **values)

    def close(self, status="normal_complete", **changes):
        values = dict(status=status, completion_reasoning="All current scoped obligations reviewed",
                      covered_gap_event_ids=[])
        values.update(changes)
        return self.fx.add("scope_close", **values)

    def test_normal_completion_requires_all_current_work_and_batch(self):
        materials, _, _ = self.ready()
        with self.assertRaisesRegex(ValueError, "CLOSE_BATCH_AND_READING_REQUIRED"):
            self.close()
        self.batch(materials)
        row = self.close()
        self.assertEqual(row["status"], "normal_complete")
        self.assertEqual(self.fx.view()["status"], "normal_complete")
        self.assertEqual(self.fx.view()["scopes"][0]["status"], "normal_complete")

    def test_filled_comparison_does_not_bypass_other_necessary_work(self):
        materials, _ = self.previous.trademark()
        self.batch(materials)
        with self.assertRaisesRegex(ValueError, "CLOSE_OBLIGATIONS_OPEN"):
            self.close()
        self.assertIn("M07_TRADEMARK_COMPARISON_PENDING", self.fx.blockers())

    def test_unprocessed_or_unrelated_batch_cannot_complete(self):
        materials, _, _ = self.ready()
        self.batch(materials, processed=[])
        self.assertIn("M07_MATERIAL_UNACCOUNTED", self.fx.blockers())
        with self.assertRaisesRegex(ValueError, "CLOSE_BATCH_AND_READING_REQUIRED"):
            self.close()
        with self.assertRaisesRegex(ValueError, "BATCH_SOURCE_UNKNOWN"):
            self.batch(materials, batch_id="UNRELATED-RUN")

    def test_unread_irrelevant_material_has_explicit_disposition(self):
        materials, _, _ = self.ready()
        extra = self.fx.material(track="public_facts", status="acquired",
                                 source_form="other", document_id="IRRELEVANT-APPENDIX")
        ids = materials + [extra["event_id"]]
        with self.assertRaisesRegex(ValueError, "BATCH_UNREAD_MATERIAL_CANNOT_COMPLETE"):
            self.batch(ids)
        self.batch(ids, unread_disposition_reasons={extra["event_id"]: {
            "kind": "out_of_scope", "reasoning": "Appendix concerns another product"}})
        self.assertNotIn("M07_MATERIAL_UNREAD", self.fx.blockers())
        self.close()
        self.assertEqual(self.fx.view()["status"], "normal_complete")

    def test_gap_requires_existing_review_and_user_request_authority(self):
        self.ready()
        with self.assertRaisesRegex(ValueError, "GAP_INVALID"):
            self.gap(existing_material_check="")
        with self.assertRaisesRegex(ValueError, "USER_FACT_FEEDBACK_REQUIRED"):
            self.gap(action_kind="user_fact", product_feedback_request_id="made-up")

    def test_one_shared_action_does_not_close_other_gap(self):
        materials, _, _ = self.ready()
        self.batch(materials)
        first = self.gap()
        second = self.gap(gap_id="G-2", question="Who owns the licensed artwork?")
        new_fact = self.fx.fact("public_facts", next(row for row in self.fx.task["distinctive_rights_events"]
            if row["kind"] == "material" and row["event_id"] == materials[1]), fact_id="F-new")
        self.follow(first, "resolved", resolved_event_ids=[new_fact["event_id"]],
                    remaining_impact="First specific question resolved")
        self.assertEqual([row["gap_id"] for row in self.fx.view()["scopes"][0]["blockers"]
                          if row["reason"] == "M07_GAP_OPEN"], ["G-2"])
        with self.assertRaisesRegex(ValueError, "CLOSE_OBLIGATIONS_OPEN"):
            self.close()
        self.follow(second, "resolved", resolved_event_ids=[new_fact["event_id"]],
                    remaining_impact="Second use separately reviewed")
        self.close()

    def test_failed_followup_needs_next_value_and_cannot_resolve(self):
        self.ready()
        gap = self.gap()
        with self.assertRaisesRegex(ValueError, "FOLLOWUP_NEXT_VALUE_REQUIRED"):
            self.follow(gap, "continue")
        with self.assertRaisesRegex(ValueError, "FOLLOWUP_RESOLUTION_REVIEW_REQUIRED"):
            self.follow(gap, "resolved", resolved_event_ids=[])
        self.follow(gap, "continue", next_value_reasoning="A different original clause is available")
        self.assertIn("M07_GAP_OPEN", self.fx.blockers())

    def test_waiting_and_limited_are_distinct_from_normal(self):
        materials, _, _ = self.ready()
        self.batch(materials)
        gap = self.gap()
        self.follow(gap, "waiting")
        self.close("waiting", covered_gap_event_ids=[gap["event_id"]])
        self.assertEqual(self.fx.view()["status"], "waiting")
        from distinctive_rights import work_entries
        waiting = [row for row in work_entries(self.fx.view()) if row["reason"] == "M07_GAP_OPEN"]
        self.assertEqual(waiting[0]["state"], "awaiting_access")
        with self.assertRaisesRegex(ValueError, "FOLLOWUP_LIMIT_BASIS_REQUIRED"):
            self.follow(gap, "limited")
        self.follow(gap, "limited", limit_kind="evidence_not_obtainable_within_scope",
                    limit_evidence="All lawful bounded sources exhausted",
                    restore_condition="New original record becomes available",
                    next_action_or_dependency="No current executable action")
        with self.assertRaisesRegex(ValueError, "CLOSE_LIMIT_BASIS_REQUIRED"):
            self.close("limited", covered_gap_event_ids=[gap["event_id"]])
        self.close("limited", covered_gap_event_ids=[gap["event_id"]],
                   limit_impact="Specific use remains unverified",
                   restore_condition="New original record becomes available",
                   no_pending_recovery=True)
        self.assertEqual(self.fx.view()["status"], "limited")
        limited = [row for row in work_entries(self.fx.view()) if row["reason"] == "M07_GAP_OPEN"]
        self.assertEqual(limited[0]["state"], "blocked")

    def test_change_pauses_handoff_and_requires_kind_matched_replacement(self):
        materials, facts, comparison = self.ready()
        self.batch(materials)
        handoff = self.fx.add("handoff", destination="09",
            result_event_ids=[comparison["event_id"]],
            handoff_reasoning="Send scoped comparison for risk review")
        change = self.fx.add("change", change_id="C-1",
            impact_reasoning="New image changes the proposed mark",
            affected_event_ids=[comparison["event_id"]], evidence_refs=["E1"])
        before = self.fx.view()["scopes"][0]["substantive_reviews"]["handoffs"][0]
        self.assertEqual(before["needs_recheck_event_ids"], [comparison["event_id"]])
        with self.assertRaisesRegex(ValueError, "CHANGE_REPLACEMENT_REQUIRED"):
            self.fx.add("change_review", change_event_id=change["event_id"], outcome="changed",
                reviewed_affected_event_ids=[comparison["event_id"]],
                recheck_reasoning="The old mark comparison changed", evidence_refs=["E1"],
                replacement_by_affected={})
        replacement = self.previous.compare(materials, facts)
        self.fx.add("change_review", change_event_id=change["event_id"], outcome="changed",
            reviewed_affected_event_ids=[comparison["event_id"]],
            recheck_reasoning="New comparison applies to current image", evidence_refs=["E1"],
            replacement_by_affected={comparison["event_id"]: [replacement["event_id"]]})
        after = self.fx.view()["scopes"][0]["substantive_reviews"]["handoffs"][0]
        self.assertEqual(after["needs_recheck_event_ids"], [comparison["event_id"]])
        self.assertEqual(handoff["destination"], "09")

    def test_local_handoff_does_not_close_scope(self):
        self.ready()
        fact = next(row for row in self.fx.task["distinctive_rights_events"] if row["kind"] == "fact")
        self.fx.add("handoff", destination="08", result_event_ids=[fact["event_id"]],
                    handoff_reasoning="Send remaining dependency only")
        self.assertEqual(self.fx.view()["status"], "in_progress")
        self.assertIn("M07_CLOSE_PENDING", self.fx.blockers())

    def test_fact_impact_pauses_dependent_handoff_but_preserves_other_fact(self):
        _, facts, comparison = self.ready()
        affected, independent = facts
        self.fx.add("handoff", destination="09",
            result_event_ids=[affected, independent, comparison["event_id"]],
            handoff_reasoning="Send scoped evidence and comparison")
        self.fx.add("impact", impact_reasoning="New record may change the first fact",
            affected_fact_event_ids=[affected], evidence_refs=["E1"])
        handoff = self.fx.view()["scopes"][0]["substantive_reviews"]["handoffs"][0]
        self.assertIn(affected, handoff["needs_recheck_event_ids"])
        self.assertIn(comparison["event_id"], handoff["needs_recheck_event_ids"])
        self.assertIn(independent, handoff["currently_usable_event_ids"])

    def test_new_material_reopens_previous_completion(self):
        materials, _, _ = self.ready()
        self.batch(materials)
        self.close()
        self.fx.material(track="public_facts", source_form="original_page", document_id="NEW-SOURCE")
        self.assertEqual(self.fx.view()["status"], "in_progress")
        self.assertIn("M07_MATERIAL_UNACCOUNTED", self.fx.blockers())

    def test_new_assessment_round_does_not_inherit_close(self):
        materials, _, _ = self.ready()
        self.batch(materials)
        self.close()
        first = next(row for row in self.fx.task["distinctive_rights_events"] if row["kind"] == "intake")
        self.fx.intake(date="2026-09-26", prior_intake_event_id=first["event_id"],
                       new_round_reasoning="Assessment date changed")
        self.assertEqual(self.fx.view()["status"], "in_progress")
        self.assertIn("M07_TRACK_FACT_PENDING", self.fx.blockers())


if __name__ == "__main__":
    unittest.main()
