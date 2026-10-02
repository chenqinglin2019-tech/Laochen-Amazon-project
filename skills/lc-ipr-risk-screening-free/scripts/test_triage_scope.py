"""05A scope, identity localization and evidence-based triage contracts."""
import unittest

import decision_workflow as workflow
import test_decision_workflow as baseline


class TriageScopeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = baseline.DecisionWorkflowTests()
        self.fixture.setUp()
        self.task = self.fixture.task
        self.candidate = self.fixture.candidate
        self.candidates = self.fixture.candidates
        self.evidence = self.fixture.evidence
        self.ledger = self.fixture.ledger
        self.task.update(candidate_identity_revision="candidate-identity-v1",
                         workflow_correction_revision="workflow-correction-v1",
                         triage_scope_revision=workflow.TRIAGE_SCOPE_REVISION,
                         product_scope_revision="object-scope-v1")
        self.task["product_scope"] = {"status": "reviewed", "objects": [{
            "object_id": "strap", "kind": "product", "relation": "target",
            "scope_status": "included", "right_types": ["patent", "design"]}],
            "facts": [], "directions": [{"direction_id": "strap-structure",
                "scenario_id": "product_entry", "right_type": "patent",
                "object_ids": ["strap"], "fact_ids": []},
                {"direction_id": "strap-appearance", "scenario_id": "product_entry",
                 "right_type": "design", "object_ids": ["strap"], "fact_ids": []}],
            "candidate_links": [{"candidate_id": "C1", "object_ids": ["strap"],
                                 "source_refs": ["E1"], "reason": "Source shows this strap"}]}

    def basis(self, *, directions=None, gaps=None, objects=None):
        value = {"product_object_ids": objects or ["strap"],
                "direction_ids": directions if directions is not None else ["strap-structure"],
                "scope_reason": "Read source E1 and mapped the strap object to this scenario",
                "evidence_refs": ["E1"], "identity_gaps": gaps if gaps is not None else []}
        if value["identity_gaps"]:
            value["identity_location"] = {
                "reason": "The retained record does not establish the missing identity field",
                "affected_work": "Country/right-specific verification remains deferred",
                "next_action": "Read the retained identity page before a bounded lookup"}
        return value

    def comparison(self, decision="selected"):
        value = {"candidate_content": "Retained record describes a strap and hook",
                 "product_content": "The scoped product has a strap and hook",
                 "relationship": "The retained structure maps to the included strap"}
        if decision == "selected":
            value["investigation_question"] = "Could the protected strap structure affect this product?"
        elif decision == "not_selected":
            value.update(difference="The retained closure is rigid while this product uses fabric",
                         applicability_limit="Only this strap in product_entry, not related family members")
        else:
            value.update(missing_fact_effect="The summary does not show the closure shape",
                         completion_condition="Read the retained figures and compare this strap",
                         existing_material_review="E1 has a title and abstract but no readable figure")
        return value

    def annotation(self, decision="selected", **changes):
        request = {"annotation_id": "D-05A-" + str(len(self.ledger["annotations"]) + 1),
                   "scenario_id": "product_entry", "decision": decision,
                   "reviewer": "offline-agent", "annotated_at": "2026-09-24T00:00:00Z",
                   "reason": "Read and compared the retained material",
                   "basis_summary": "Concrete product-to-candidate comparison",
                   "reading_level": "result_record", "evidence_refs": ["E1"],
                   "reopen_conditions": ["New protection content or product scope"],
                   "candidate_relation": self.basis(), "comparison": self.comparison(decision)}
        request.update(changes)
        return workflow.make_annotation(self.task, "patents", self.candidate,
                                        request, evidence=self.evidence)

    def test_unknown_country_has_one_unlocated_triage_and_selected_waits_for_identity(self):
        self.candidate["jurisdiction"] = "unknown"
        summary = workflow.triage_summary(self.task, self.candidates, self.ledger,
                                          evidence=self.evidence)
        self.assertEqual([row["jurisdiction"] for row in summary["records"]], [workflow.UNLOCATED])
        incomplete = self.basis(gaps=["target_jurisdiction"])
        incomplete.pop("identity_location")
        with self.assertRaisesRegex(ValueError, "IDENTITY_LOCATION_REQUIRED"):
            self.annotation(candidate_relation=incomplete)
        row = self.annotation(candidate_relation=self.basis(gaps=["target_jurisdiction"]))
        self.ledger["annotations"].append(row)
        summary = workflow.triage_summary(self.task, self.candidates, self.ledger,
                                          evidence=self.evidence)
        self.assertEqual(summary["counts"]["selected"], 1)
        self.assertEqual(workflow.effective_selected_candidates(self.task, self.candidates,
                         self.ledger, evidence=self.evidence), [])
        from workflow_v24 import derive_work_view
        work = derive_work_view(self.task, self.evidence, self.candidates,
                                {"queries": {}}, self.ledger, coverage=[])
        self.assertTrue(any(item.get("candidate_id") == "C1" and
            item.get("reason") == "CANDIDATE_IDENTITY_DIRECTION_PENDING"
            for item in work["entries"]))
        self.assertTrue(any(item.get("identity_location", {}).get("next_action")
            for item in work["entries"] if item.get("candidate_id") == "C1"))
        self.candidate["jurisdiction"] = "US"
        summary = workflow.triage_summary(self.task, self.candidates, self.ledger,
                                          evidence=self.evidence)
        self.assertEqual(next(item for item in summary["records"]
                              if item["jurisdiction"] == "US")["decision"], "unreviewed")

    def test_partial_number_can_be_selected_and_vague_content_remains_needs_info(self):
        self.candidate.pop("publication_number")
        selected = self.annotation(candidate_relation=self.basis(gaps=["publication_number"]))
        self.assertEqual(selected["decision"], "selected")
        self.ledger["annotations"].append(selected)
        self.assertEqual(workflow.triage_summary(self.task, self.candidates, self.ledger,
                         evidence=self.evidence)["counts"]["selected"], 1)
        # The next retained summary cannot establish a concrete product relation.
        # Its own decision records what has already been read and the exact
        # figure needed, without turning a source-read failure into exclusion.
        self.ledger["annotations"].clear()
        waiting = self.annotation("needs_info",
            missing_information=["Retained figure showing the closure"],
            next_actions=[{"action_id": "READ-FIGURE", "kind": "agent_read",
                "purpose": "Read the retained closure figure", "max_attempts": 1,
                "required_facts": ["representative_figures"],
                "reading_scope": {"level": "representative_figures", "page_numbers": [1]},
                "evidence_refs": ["E1"]}])
        self.ledger["annotations"].append(waiting)
        self.assertEqual(workflow.triage_summary(self.task, self.candidates, self.ledger,
                         evidence=self.evidence)["counts"]["needs_info"], 1)

    def test_unknown_right_can_be_selected_as_association_without_deep_dispatch(self):
        self.candidate["right_type"] = "unknown"
        row = self.annotation(candidate_relation=self.basis(
            directions=["strap-structure"], gaps=["right_type"]))
        self.ledger["annotations"].append(row)
        self.assertEqual(workflow.triage_summary(self.task, self.candidates, self.ledger,
                         evidence=self.evidence)["counts"]["selected"], 1)
        self.assertEqual(workflow.effective_selected_candidates(self.task, self.candidates,
                         self.ledger, evidence=self.evidence), [])
        with self.assertRaisesRegex(ValueError, "DIRECTION_BASIS_INVALID"):
            self.annotation(candidate_relation=self.basis(directions=["invented"], gaps=["right_type"]))

    def test_generic_exclusion_and_unread_scope_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "EXCLUSION_DIFFERENCE_AND_SCOPE_REQUIRED"):
            self.annotation("not_selected", comparison={"candidate_content": "No match",
                "product_content": "No match", "relationship": "No match"})
        with self.assertRaisesRegex(ValueError, "OBJECT_SCOPE_NOT_INCLUDED"):
            self.annotation(candidate_relation=self.basis(objects=["other"]))
        self.task["product_scope"]["objects"][0]["scope_status"] = "user_excluded"
        summary = workflow.triage_summary(self.task, self.candidates, self.ledger,
                                          evidence=self.evidence)
        self.assertEqual(summary["records"], [])
        self.assertEqual(summary["scope_dispositions"][0]["scope_status"], "user_excluded")

    def test_partial_scope_keeps_excluded_object_separate_and_second_country_needs_review(self):
        data = self.task["product_scope"]
        data["objects"].append({"object_id": "photo", "kind": "photograph",
            "relation": "reference", "scope_status": "default_excluded",
            "right_types": ["patent"]})
        data["candidate_links"][0]["object_ids"].append("photo")
        summary = workflow.triage_summary(self.task, self.candidates, self.ledger,
                                          evidence=self.evidence)
        self.assertEqual(len(summary["records"]), 1)
        self.assertEqual(summary["scope_dispositions"][0]["object_id"], "photo")
        self.assertEqual(summary["scope_dispositions"][0]["scope_status"], "default_excluded")
        self.ledger["annotations"].append(self.annotation())
        with self.assertRaisesRegex(ValueError, "IDENTITY_GAPS_REQUIRED"):
            self.annotation(jurisdiction="GB")
        self.ledger["annotations"].append(self.annotation(
            jurisdiction="GB", candidate_relation=self.basis(gaps=["target_jurisdiction"])))
        summary = workflow.triage_summary(self.task, self.candidates, self.ledger,
                                          evidence=self.evidence)
        self.assertEqual({row["jurisdiction"] for row in summary["records"]}, {"US", "GB"})
        self.assertEqual(summary["counts"]["selected"], 2)
        self.assertEqual(len(workflow.effective_selected_candidates(self.task, self.candidates,
                         self.ledger, evidence=self.evidence)), 1)
        from workflow_v24 import derive_work_view
        work = derive_work_view(self.task, self.evidence, self.candidates,
                                {"queries": {}}, self.ledger, coverage=[])
        self.assertTrue(any(item.get("jurisdiction") == "GB" and
            item.get("reason") == "CANDIDATE_IDENTITY_DIRECTION_PENDING"
            for item in work["entries"]))


if __name__ == "__main__":
    unittest.main()
