"""07A intake, parallel tracks, source time and scoped reuse contracts."""
from pathlib import Path
from datetime import datetime
import tempfile
import unittest
from unittest.mock import patch

from common import atomic_write_json, load_json
from candidate_triage_stage import record_selected_handoff
from distinctive_rights import REVISION, project, record
import decision_workflow as workflow
import test_triage_scope as base


class DistinctiveRightsTests(unittest.TestCase):
    def setUp(self):
        self.right_type = "trademark_word"
        self.object_id = "logo"
        fixture = base.TriageScopeTests()
        fixture.setUp()
        fixture.fixture.use_trademark()
        self.task, self.candidate = fixture.task, fixture.candidate
        self.evidence, self.candidates, self.ledger = fixture.evidence, fixture.fixture.candidates, fixture.ledger
        self.task.update(triage_followup_revision="candidate-followup-v1",
                         triage_stage_revision="candidate-triage-stage-v1",
                         distinctive_rights_revision=REVISION)
        self.task["product_scope"]["objects"] = [{"object_id": "logo", "kind": "logo",
            "relation": "own", "scope_status": "included", "right_types": ["trademark_word"]}]
        self.task["product_scope"]["directions"] = [{"direction_id": "mark-use",
            "scenario_id": "product_entry", "right_type": "trademark_word",
            "object_ids": ["logo"], "fact_ids": []}]
        self.task["product_scope"]["candidate_links"] = [{"candidate_id": "C1",
            "object_ids": ["logo"], "source_refs": ["E1"], "reason": "Actual intended mark"}]
        self.candidate["sources"] = [{"evidence_id": "E1", "source_anchor": "import-row-1"}]
        request = {"annotation_id": "D-M07", "scenario_id": "product_entry", "decision": "selected",
            "reviewer": "agent", "annotated_at": "2026-09-25T00:00:00Z",
            "reason": "Reviewed mark and retained candidate", "basis_summary": "Concrete mark association",
            "reading_level": "result_record", "evidence_refs": ["E1"],
            "reopen_conditions": ["Changed mark or candidate"],
            "candidate_relation": fixture.basis(objects=["logo"], directions=["mark-use"]),
            "comparison": fixture.comparison()}
        annotation = workflow.make_annotation(self.task, "trademarks", self.candidate,
                                               request, evidence=self.evidence)
        self.ledger["annotations"].append(annotation)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.save()
        handoff = record_selected_handoff(self.path, {**self.scope(),
            "annotation_id": annotation["annotation_id"], "evidence_refs": ["E1"],
            "reading_scope": {"level": "result_record", "sections": ["mark"]},
            "verification_gaps": [], "reviewer": "agent", "reason": "Selected mark for specialty"})
        self.handoff_id = handoff["event_id"]
        self.refresh()

    def scope(self):
        return {"candidate_id": "C1", "scenario_id": "product_entry",
                "jurisdiction": "US", "right_type": self.right_type}

    def save(self):
        for name, value in (("task", self.task), ("evidence", self.evidence),
                            ("normalized-candidates", self.candidates),
                            ("materiality-annotations", self.ledger), ("search-plan", {"queries": {}})):
            atomic_write_json(self.path / (name + ".json"), value)

    def refresh(self):
        self.task = load_json(self.path / "task.json")

    def add(self, kind, **fields):
        request = {**self.scope(), "kind": kind, "reviewer": "agent",
                   "reason": "Reviewed the retained scope and source", **fields}
        if kind != "intake":
            request.setdefault("intake_event_id", self.intake_id)
            request.setdefault("assessment_date", self.assessment_date)
        row = record(self.path, request)
        self.refresh()
        return row

    def intake(self, *, tracks=None, date="2026-09-25", **changes):
        self.assessment_date = date
        values = dict(selected_handoff_event_id=self.handoff_id,
            assessment_date=date, object_id=self.object_id, subject_id="mark-1",
            subject_version="logo-v1", use_context="mark on sold strap",
            subject_evidence_refs=["E1"], tracks=tracks or {
                "registration": {"needed": True, "reasoning": "Check identified registered mark"},
                "public_facts": {"needed": True, "reasoning": "Check actual use independently"}})
        values.update(changes)
        row = self.add("intake", **values)
        self.intake_id = row["event_id"]
        return row

    def material(self, *, track="registration", status="sufficient_for_listed_tracks", **changes):
        values = dict(document_id="US-MARK-1", document_version="v1", evidence_refs=["E1"],
            acquired_at="2026-09-01T00:00:00Z", source_form="official_register",
            tracks=[track], reading_locations=["record page 1"] if status != "acquired" else [],
            status=status, support_reasoning="Actually read for this track")
        values.update(changes)
        return self.add("material", **values)

    def fact(self, track, material, **changes):
        values = dict(fact_id="F-" + track, track=track, outcome="supported",
            statement="Source establishes the stated fact only", as_of_reasoning="Checked for the fixed assessment date",
            evidence_refs=material["evidence_refs"], material_event_ids=[material["event_id"]],
            time_points=[])
        if track == "registration":
            values.update(right_identity="US-MARK-1", source_checked_at="2026-09-25T01:00:00Z")
        values.update(changes)
        return self.add("fact", **values)

    def view(self):
        return project(self.task, self.evidence, self.candidates, self.ledger)

    def blockers(self):
        return [row["reason"] for row in self.view()["scopes"][0]["blockers"]]

    def test_current_handoff_object_and_fixed_date(self):
        with self.assertRaisesRegex(ValueError, "CURRENT_HANDOFF"):
            self.add("intake", selected_handoff_event_id="wrong", assessment_date="2026-09-25",
                object_id="logo", subject_id="mark-1", subject_version="v1",
                use_context="sold product", subject_evidence_refs=["E1"], tracks={})
        with self.assertRaisesRegex(ValueError, "INCLUDED_OBJECT"):
            self.intake(object_id="reference-logo")
        self.intake()
        with self.assertRaisesRegex(ValueError, "ASSESSMENT_DATE_CHANGED"):
            self.material(assessment_date="2026-09-26")

    def test_subject_binds_reviewed_inventory_when_present(self):
        self.task["product"]["mark_inventory"] = [{"mark_id": "mark-real",
            "form": "plain_text", "graphic_description": "TEST", "scenario_ids": ["product_entry"],
            "evidence_refs": ["E1"]}]
        self.save()
        with self.assertRaisesRegex(ValueError, "SUBJECT_INVENTORY_BINDING_REQUIRED"):
            self.intake()
        self.intake(subject_id="mark-real")

    def test_missing_assessment_date_defaults_only_at_intake(self):
        row = self.add("intake", selected_handoff_event_id=self.handoff_id,
            object_id="logo", subject_id="mark-1", subject_version="logo-v1",
            use_context="mark on sold strap", subject_evidence_refs=["E1"],
            tracks={"registration": {"needed": True, "reasoning": "Check register"},
                    "public_facts": {"needed": True, "reasoning": "Check use"}})
        self.assertEqual(row["assessment_date"], datetime.now().astimezone().date().isoformat())
        self.assertEqual(row["assessment_date_basis"], "module_07_start_local_date")

    def test_registration_and_public_facts_advance_independently(self):
        self.intake()
        material = self.material()
        self.fact("registration", material)
        self.assertEqual([row["track"] for row in self.view()["scopes"][0]["blockers"]
                          if row["reason"] == "M07_TRACK_FACT_PENDING"], ["public_facts"])
        public = self.material(track="public_facts", source_form="original_page",
                               document_id="PUBLIC-1")
        self.fact("public_facts", public)
        self.assertNotIn("M07_TRACK_FACT_PENDING", self.blockers())
        self.assertIn("M07_CLOSE_PENDING", self.blockers())
        self.assertEqual(self.view()["status"], "in_progress")

    def test_download_and_summary_do_not_prove_registration(self):
        self.intake()
        acquired = self.material(status="acquired")
        with self.assertRaisesRegex(ValueError, "PURPOSE_READING_REQUIRED"):
            self.fact("registration", acquired)
        summary = self.material(source_form="summary", document_id="SUMMARY-1")
        with self.assertRaisesRegex(ValueError, "REGISTRATION_OFFICIAL_BASIS_REQUIRED"):
            self.fact("registration", summary)
        self.assertIn("M07_MATERIAL_UNREAD", self.blockers())

    def test_no_result_cannot_close_other_track_or_stage(self):
        self.intake()
        self.evidence["source_runs"] = [{"run_id": "RUN-0", "jurisdiction": "US", "status": "no_result"}]
        self.save()
        self.add("observation", track="registration", outcome="no_result",
                 source_run_id="RUN-0", reasoning="Actual register lookup returned zero")
        self.assertEqual(self.view()["scopes"][0]["observations"][0]["outcome"], "no_result")
        self.assertEqual([row["track"] for row in self.view()["scopes"][0]["blockers"]
                          if row["reason"] == "M07_TRACK_FACT_PENDING"],
                         ["registration", "public_facts"])

    def test_fact_preserves_distinct_time_meanings(self):
        self.intake()
        material = self.material(track="public_facts", source_form="original_page")
        fact = self.fact("public_facts", material, time_points=[{
            "kind": "page_label", "date": "2020-01-01", "meaning": "Page label only",
            "evidence_refs": ["E1"]}, {"kind": "historical_publication", "date": "2021-02-03",
            "meaning": "Verified archived appearance", "evidence_refs": ["E1"]}])
        self.assertEqual(fact["assessment_date"], "2026-09-25")
        self.assertEqual(material["acquired_at"], "2026-09-01T00:00:00Z")
        self.assertEqual(fact["time_points"][0]["kind"], "page_label")

    def test_new_round_does_not_reuse_old_fact(self):
        first = self.intake()
        material = self.material()
        self.fact("registration", material)
        with self.assertRaisesRegex(ValueError, "NEW_ROUND_REVIEW_REQUIRED"):
            self.intake(date="2026-09-26")
        self.intake(date="2026-09-26", prior_intake_event_id=first["event_id"],
                    new_round_reasoning="Assessment date changed")
        self.assertEqual([row["track"] for row in self.view()["scopes"][0]["blockers"]
                          if row["reason"] == "M07_TRACK_FACT_PENDING"],
                         ["registration", "public_facts"])

    def test_new_event_pauses_only_affected_fact(self):
        self.intake()
        registered = self.fact("registration", self.material())
        public = self.fact("public_facts", self.material(track="public_facts", source_form="original_page"))
        impact = self.add("impact", impact_reasoning="New registry event may change status",
                          affected_fact_event_ids=[registered["event_id"]], evidence_refs=["E1"])
        rows = {row["event_id"]: row for row in self.view()["scopes"][0]["facts"]}
        self.assertFalse(rows[registered["event_id"]]["currently_usable"])
        self.assertTrue(rows[public["event_id"]]["currently_usable"])
        self.add("impact_review", impact_event_id=impact["event_id"], outcome="continues",
                 reviewed_affected_fact_event_ids=[registered["event_id"]],
                 recheck_reasoning="Official event leaves the supported fact applicable", evidence_refs=["E1"])
        self.assertNotIn("M07_IMPACT_REVIEW_PENDING", self.blockers())

    def test_changed_event_needs_same_track_replacement(self):
        self.intake()
        material = self.material()
        old = self.fact("registration", material)
        impact = self.add("impact", impact_reasoning="New registry event may alter status",
                          affected_fact_event_ids=[old["event_id"]], evidence_refs=["E1"])
        with self.assertRaisesRegex(ValueError, "IMPACT_REPLACEMENT_REQUIRED"):
            self.add("impact_review", impact_event_id=impact["event_id"], outcome="changed",
                     reviewed_affected_fact_event_ids=[old["event_id"]],
                     recheck_reasoning="Old status no longer supported", evidence_refs=["E1"],
                     replacement_by_affected={})
        replacement = self.fact("registration", material, fact_id="F-status-unknown",
                                outcome="unknown")
        self.add("impact_review", impact_event_id=impact["event_id"], outcome="changed",
                 reviewed_affected_fact_event_ids=[old["event_id"]],
                 recheck_reasoning="New event leaves current status unknown", evidence_refs=["E1"],
                 replacement_by_affected={old["event_id"]: [replacement["event_id"]]})
        self.assertNotIn(old["event_id"], [row["event_id"] for row in self.view()["scopes"][0]["facts"]])
        self.assertIn("M07_TRACK_FACT_PENDING", self.blockers())

    def test_action_card_points_to_local_recorder(self):
        from advance_work import action_card
        from distinctive_rights import work_entries
        card = action_card(self.path, work_entries(self.view())[0])
        self.assertEqual(card["action"], "review_distinctive_rights")
        self.assertTrue(card["recorder"].endswith("record_distinctive_rights.py"))

    def test_current_07_work_enters_shared_queue(self):
        from workflow_v24 import resolved_work_view
        with patch("product_scope.project_work", side_effect=lambda task, view, plan: view):
            view = resolved_work_view(self.task, self.evidence, self.candidates,
                                      {"queries": {}}, self.ledger)
        self.assertEqual(view["distinctive_rights"]["revision"], REVISION)
        self.assertEqual(view["status"], "incomplete")
        self.assertIn("M07_INTAKE_PENDING", [row.get("reason") for row in view["entries"]])

    def test_copyright_without_registration_can_continue_public_source(self):
        self.right_type, self.object_id = "copyright", "art"
        self.candidate["right_type"] = "copyright"
        self.candidates = {"patents": [], "trademarks": [],
                           "copyright_assets": [self.candidate], "enforcement": []}
        self.task["candidate_triage_stage_events"] = []
        self.task["product_scope"]["objects"] = [{"object_id": "art", "kind": "pattern",
            "relation": "integrated", "scope_status": "included", "right_types": ["copyright"]}]
        self.task["product_scope"]["directions"] = [{"direction_id": "art-source",
            "scenario_id": "product_entry", "right_type": "copyright",
            "object_ids": ["art"], "fact_ids": []}]
        self.task["product_scope"]["candidate_links"] = [{"candidate_id": "C1",
            "object_ids": ["art"], "source_refs": ["E1"], "reason": "Retained art source"}]
        self.ledger["annotations"] = []
        annotation = workflow.make_annotation(self.task, "copyright_assets", self.candidate, {
            "annotation_id": "D-M07-COPY", "scenario_id": "product_entry", "decision": "selected",
            "reviewer": "agent", "annotated_at": "2026-09-25T00:00:00Z",
            "reason": "Reviewed concrete art", "basis_summary": "Art association",
            "reading_level": "result_record", "evidence_refs": ["E1"],
            "reopen_conditions": ["New original work"],
            "candidate_relation": {"product_object_ids": ["art"], "direction_ids": ["art-source"],
                "scope_reason": "Source shows art", "evidence_refs": ["E1"], "identity_gaps": []},
            "comparison": {"candidate_content": "Retained art", "product_content": "Used art",
                "relationship": "Concrete correspondence", "investigation_question": "Source?"}},
            evidence=self.evidence)
        self.ledger["annotations"].append(annotation)
        self.save()
        handoff = record_selected_handoff(self.path, {**self.scope(),
            "annotation_id": annotation["annotation_id"], "evidence_refs": ["E1"],
            "reading_scope": {"level": "result_record", "sections": ["art"]},
            "verification_gaps": ["owner_identity"], "reviewer": "agent",
            "reason": "Continue source investigation without a registration number"})
        self.handoff_id = handoff["event_id"]
        self.refresh()
        self.intake(tracks={"registration": {"needed": False,
            "reasoning": "No relevant registration route established for this work"},
            "public_facts": {"needed": True, "reasoning": "Trace actual public source"}})
        public = self.material(track="public_facts", source_form="original_page")
        self.fact("public_facts", public)
        self.assertNotIn("M07_TRACK_FACT_PENDING", self.blockers())
        self.assertIn("M07_HANDOFF_GAP_OPEN", self.blockers())
        self.assertEqual(self.view()["status"], "in_progress")

    def test_reused_m06_material_preserves_original_acquisition_time(self):
        from specialty_analysis import _append as append_m06
        prior = append_m06(self.task, "material", {**self.scope(), "right_type": "design",
            "document_id": "SHARED-1", "document_version": "v1", "evidence_refs": ["E1"],
            "acquired_at": "2026-09-01T00:00:00Z"})
        self.save()
        self.intake()
        common = dict(document_id="SHARED-1", document_version="v1",
                      reuse_from_event_id=prior["event_id"],
                      reuse_applicability_reasoning="Same original is relevant to this mark's public use")
        reused = self.material(track="public_facts", source_form="original_page", **common)
        self.assertEqual(reused["acquired_at"], prior["acquired_at"])
        with self.assertRaisesRegex(ValueError, "REUSE_BASIS_INVALID"):
            self.material(track="public_facts", source_form="original_page",
                          acquired_at="2026-09-25T00:00:00Z", **common)


if __name__ == "__main__":
    unittest.main()
