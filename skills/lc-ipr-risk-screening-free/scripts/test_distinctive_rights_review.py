"""07B scoped trademark comparison and copyright provenance/permission contracts."""
import unittest

from candidate_triage_stage import record_selected_handoff
import decision_workflow as workflow
import test_distinctive_rights as prior


def judgment(outcome="unknown", *, refs=None):
    row = {"outcome": outcome, "reasoning": "Reviewed the actual item separately",
           "evidence_refs": ["E1"] if refs is None else refs}
    if outcome in {"unknown", "not_applicable"}:
        row["dependency_or_basis"] = "Actual source does not settle this dimension"
    return row


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.fx = prior.DistinctiveRightsTests()
        self.fx.setUp()
        self.addCleanup(self.fx.tmp.cleanup)

    def trademark(self, form="plain_text"):
        f = self.fx
        f.task["product"]["mark_inventory"] = [{"mark_id": "mark-1", "form": form,
            "graphic_description": "Actual proposed mark", "scenario_ids": ["product_entry"],
            "evidence_refs": ["E1"]}]
        f.save()
        f.intake()
        official = f.material()
        registered = f.fact("registration", official)
        actual = f.material(track="public_facts", source_form="product_original", document_id="PRODUCT-MARK")
        used = f.fact("public_facts", actual)
        return [official["event_id"], actual["event_id"]], [registered["event_id"], used["event_id"]]

    def compare(self, materials, facts, *, form="plain_text", **changes):
        dimensions = {key: judgment("corresponds") for key in (
            "overall", "text", "pronunciation", "meaning", "graphic",
            "goods_services", "actual_use", "specimen")}
        if form == "plain_text":
            dimensions["graphic"] = judgment("not_applicable")
        values = dict(mark_form=form, mark_version="logo-v1", use_context="mark on sold strap",
            candidate_sign_description="The actual reviewed candidate mark", dimensions=dimensions,
            components=[], material_event_ids=materials, fact_event_ids=facts,
            evidence_refs=["E1"])
        values.update(changes)
        return self.fx.add("trademark_comparison", **values)

    def copyright(self, right_type="copyright"):
        f = self.fx
        f.right_type, f.object_id = right_type, "art"
        f.candidate["right_type"] = right_type
        f.candidates = {"patents": [], "trademarks": [],
                        "copyright_assets": [f.candidate], "enforcement": []}
        f.task["candidate_triage_stage_events"] = []
        f.task["product_scope"]["objects"] = [{"object_id": "art", "kind": "pattern",
            "relation": "integrated", "scope_status": "included", "right_types": [right_type]}]
        f.task["product_scope"]["directions"] = [{"direction_id": "art-source",
            "scenario_id": "product_entry", "right_type": right_type,
            "object_ids": ["art"], "fact_ids": []}]
        f.task["product_scope"]["candidate_links"] = [{"candidate_id": "C1",
            "object_ids": ["art"], "source_refs": ["E1"], "reason": "Retained art source"}]
        f.task["product"]["assets"] = [{"asset_id": "art-1", "right_types": [right_type],
            "scenario_ids": ["product_entry"], "evidence_refs": ["E1"]}]
        f.ledger["annotations"] = []
        annotation = workflow.make_annotation(f.task, "copyright_assets", f.candidate, {
            "annotation_id": "D-M07-COPY", "scenario_id": "product_entry", "decision": "selected",
            "reviewer": "agent", "annotated_at": "2026-09-25T00:00:00Z",
            "reason": "Reviewed concrete art", "basis_summary": "Art association",
            "reading_level": "result_record", "evidence_refs": ["E1"],
            "reopen_conditions": ["New original work"],
            "candidate_relation": {"product_object_ids": ["art"], "direction_ids": ["art-source"],
                "scope_reason": "Source shows art", "evidence_refs": ["E1"], "identity_gaps": []},
            "comparison": {"candidate_content": "Retained art", "product_content": "Used art",
                "relationship": "Concrete correspondence", "investigation_question": "Source?"}},
            evidence=f.evidence)
        f.ledger["annotations"].append(annotation)
        f.save()
        handoff = record_selected_handoff(f.path, {**f.scope(),
            "annotation_id": annotation["annotation_id"], "evidence_refs": ["E1"],
            "reading_scope": {"level": "result_record", "sections": ["art"]},
            "verification_gaps": [], "reviewer": "agent", "reason": "Selected art"})
        f.handoff_id = handoff["event_id"]
        f.refresh()
        f.intake(subject_id="art-1", subject_version="art-v1", use_context="printed on strap",
            tracks={"registration": {"needed": False, "reasoning": "No relevant registration identified"},
                    "public_facts": {"needed": True, "reasoning": "Trace actual source"}})
        original = f.material(track="public_facts", source_form="original_page", document_id="PAGE-1")
        fact = f.fact("public_facts", original)
        return original, fact

    def source(self, material, fact, **changes):
        values = dict(intended_asset_version="art-v1", source_work_id="WORK-1",
            source_work_version="work-v2", actually_reviewed_content="Red bird illustration",
            content_location="page image 1", version_correspondence_reasoning="Compared actual pixels",
            time_points=[{"kind": "page_label", "date": "2020-01-01", "meaning": "Page label only",
                          "evidence_refs": ["E1"]}], material_event_ids=[material["event_id"]],
            fact_event_ids=[fact["event_id"]], evidence_refs=["E1"])
        values.update(changes)
        return self.fx.add("copyright_source", **values)

    def relationship(self, source, materials, facts, **changes):
        parties = {role: judgment() for role in ("publisher", "author", "owner", "licensor")}
        questions = {key: judgment() for key in ("protectable_expression",
            "expression_correspondence", "access_or_copying", "independent_creation")}
        values = dict(source_event_id=source["event_id"], parties=parties, questions=questions,
            material_event_ids=materials, fact_event_ids=facts, evidence_refs=["E1"])
        values.update(changes)
        return self.fx.add("copyright_relationship", **values)

    def license(self, materials, facts, **changes):
        source = next(row for row in reversed(self.fx.task["distinctive_rights_events"])
                      if row["kind"] == "copyright_source")
        coverage = {key: judgment() for key in ("licensor_authority", "licensee", "asset_version",
            "use", "jurisdiction", "term", "modification", "sublicense")}
        values = dict(intended_asset_version="art-v1", requested_use="printed on strap",
            requested_jurisdiction="US", requested_licensee="Seller LLC", coverage=coverage,
            source_event_id=source["event_id"], licensed_source_work_id="WORK-1",
            licensed_source_work_version="work-v2",
            overall_coverage="unknown", material_event_ids=materials,
            fact_event_ids=facts, evidence_refs=["E1"])
        values.update(changes)
        return self.fx.add("copyright_license", **values)

    def test_trademark_unit_and_dimensions_are_explicit(self):
        materials, facts = self.trademark()
        with self.assertRaisesRegex(ValueError, "TRADEMARK_UNIT_INVALID"):
            self.compare(materials, facts, mark_version="other-logo")
        with self.assertRaisesRegex(ValueError, "TRADEMARK_DIMENSIONS_REQUIRED"):
            self.compare(materials, facts, dimensions={"overall": judgment("corresponds")})
        row = self.compare(materials, facts)
        self.assertEqual(row["mark_version"], "logo-v1")
        self.assertEqual(self.fx.view()["scopes"][0]["substantive_reviews"]["trademark_comparison_event_id"], row["event_id"])

    def test_composite_requires_graphic_parts_and_relation(self):
        materials, facts = self.trademark("composite")
        with self.assertRaisesRegex(ValueError, "COMPOSITION_REQUIRED"):
            self.compare(materials, facts, form="composite")
        parts = [{"kind": kind, "component_id": kind + "-1", "comparison": judgment("differs")}
                 for kind in ("text", "graphic")]
        row = self.compare(materials, facts, form="composite", components=parts,
            composition_relation=judgment("differs"))
        self.assertEqual(len(row["components"]), 2)

    def test_unknown_use_cannot_be_recast_as_overall_difference(self):
        materials, facts = self.trademark()
        dimensions = {key: judgment("corresponds") for key in (
            "overall", "text", "pronunciation", "meaning", "graphic",
            "goods_services", "actual_use", "specimen")}
        dimensions["actual_use"] = judgment()
        with self.assertRaisesRegex(ValueError, "OVERALL_UNSUPPORTED"):
            self.compare(materials, facts, dimensions=dimensions)
        dimensions["overall"] = judgment()
        self.compare(materials, facts, dimensions=dimensions)
        self.assertIn("M07_TRADEMARK_DIMENSION_OPEN", self.fx.blockers())

    def test_specimen_needs_actual_official_material(self):
        materials, facts = self.trademark()
        with self.assertRaisesRegex(ValueError, "SPECIMEN_OFFICIAL_REQUIRED"):
            self.compare(materials[1:], facts, material_event_ids=materials[1:])

    def test_public_mark_comparison_can_continue_without_registration(self):
        f = self.fx
        f.intake(tracks={"registration": {"needed": False, "reasoning": "No registration clue"},
                         "public_facts": {"needed": True, "reasoning": "Review actual public use"}})
        material = f.material(track="public_facts", source_form="original_page")
        fact = f.fact("public_facts", material)
        dimensions = {key: judgment("unknown") for key in (
            "overall", "text", "pronunciation", "meaning", "graphic",
            "goods_services", "actual_use", "specimen")}
        dimensions["specimen"] = judgment("not_applicable")
        row = self.compare([material["event_id"]], [fact["event_id"]], dimensions=dimensions)
        self.assertEqual(row["dimensions"]["specimen"]["outcome"], "not_applicable")
        self.assertIn("M07_TRADEMARK_DIMENSION_OPEN", f.blockers())

    def test_review_is_paused_when_its_fact_changes(self):
        materials, facts = self.trademark()
        self.compare(materials, facts)
        self.fx.add("impact", impact_reasoning="New product mark version",
                    affected_fact_event_ids=[facts[1]], evidence_refs=["E1"])
        self.assertIn("M07_TRADEMARK_COMPARISON_RECHECK_PENDING", self.fx.blockers())

    def test_source_date_does_not_become_first_publication(self):
        material, fact = self.copyright()
        with self.assertRaisesRegex(ValueError, "HISTORY_CONTENT_REQUIRED"):
            self.source(material, fact, time_points=[{"kind": "historical_publication",
                "date": "2020-01-01", "meaning": "Archived page", "evidence_refs": ["E1"]}])
        with self.assertRaisesRegex(ValueError, "EARLIEST_OVERCLAIM"):
            self.source(material, fact, earliest_found={"date": "2020-01-01",
                "content_correspondence": "Current image", "claim": "first_publication"})
        row = self.source(material, fact)
        self.assertEqual(row["time_points"][0]["kind"], "page_label")

    def test_party_roles_and_expression_questions_stay_separate(self):
        material, fact = self.copyright()
        source = self.source(material, fact)
        parties = {role: judgment() for role in ("publisher", "author", "owner", "licensor")}
        parties["publisher"] = {**judgment("supported"), "identity": "Example site",
                                "relationship_basis": "Page publisher only"}
        row = self.relationship(source, [material["event_id"]], [fact["event_id"]], parties=parties)
        self.assertEqual(row["parties"]["owner"]["outcome"], "unknown")
        self.assertIn("M07_COPYRIGHT_PARTY_OPEN", self.fx.blockers())
        parties["owner"] = {**judgment("supported"), "identity": "Example site",
                            "relationship_basis": "Same name on page"}
        with self.assertRaisesRegex(ValueError, "RIGHTS_CHAIN_REQUIRED"):
            self.relationship(source, [material["event_id"]], [fact["event_id"]], parties=parties)

    def test_visual_similarity_does_not_set_copying_or_independence(self):
        material, fact = self.copyright()
        source = self.source(material, fact)
        questions = {key: judgment() for key in ("protectable_expression",
            "expression_correspondence", "access_or_copying", "independent_creation")}
        questions["expression_correspondence"] = judgment("supported")
        row = self.relationship(source, [material["event_id"]], [fact["event_id"]], questions=questions)
        self.assertEqual(row["questions"]["access_or_copying"]["outcome"], "unknown")
        self.assertEqual(row["questions"]["independent_creation"]["outcome"], "unknown")

    def test_partial_license_does_not_cover_other_use(self):
        material, fact = self.copyright()
        source = self.source(material, fact)
        self.relationship(source, [material["event_id"]], [fact["event_id"]])
        license_material = self.fx.material(track="public_facts", source_form="license", document_id="LICENSE-1")
        coverage = {key: judgment("covered") for key in ("licensor_authority", "licensee",
            "asset_version", "use", "jurisdiction", "term", "modification", "sublicense")}
        coverage["use"] = judgment()
        with self.assertRaisesRegex(ValueError, "LICENSE_OVERCLAIM"):
            self.license([license_material["event_id"]], [fact["event_id"]], coverage=coverage,
                         overall_coverage="covered", license_start="2026-01-01")
        row = self.license([license_material["event_id"]], [fact["event_id"]], coverage=coverage,
                           overall_coverage="partial", license_start="2026-01-01")
        self.assertEqual(row["overall_coverage"], "partial")
        self.assertIn("M07_COPYRIGHT_LICENSE_SCOPE_OPEN", self.fx.blockers())

    def test_purchase_or_generic_commercial_claim_cannot_prove_license(self):
        material, fact = self.copyright()
        source = self.source(material, fact)
        self.relationship(source, [material["event_id"]], [fact["event_id"]])
        coverage = {key: judgment("covered") for key in ("licensor_authority", "licensee",
            "asset_version", "use", "jurisdiction", "term", "modification", "sublicense")}
        with self.assertRaisesRegex(ValueError, "LICENSE_INSTRUMENT_REQUIRED"):
            self.license([material["event_id"]], [fact["event_id"]], coverage=coverage,
                         overall_coverage="covered", license_start="2026-01-01")
        with self.assertRaisesRegex(ValueError, "LICENSE_SCOPE_INVALID"):
            self.license([material["event_id"]], [fact["event_id"]], requested_use="commercial use")
        with self.assertRaisesRegex(ValueError, "LICENSE_WORK_BINDING_REQUIRED"):
            self.license([material["event_id"]], [fact["event_id"]],
                         licensed_source_work_version="other-work")

    def test_full_coverage_requires_authority_and_current_term(self):
        material, fact = self.copyright()
        source = self.source(material, fact)
        license_material = self.fx.material(track="public_facts", source_form="license", document_id="LICENSE-1")
        parties = {role: judgment() for role in ("publisher", "author", "owner", "licensor")}
        parties["licensor"] = {**judgment("supported"), "identity": "Licensor LLC",
                               "relationship_basis": "Read authorization chain"}
        relation = self.relationship(source, [material["event_id"], license_material["event_id"]],
                                     [fact["event_id"]], parties=parties)
        coverage = {key: judgment("covered") for key in ("licensor_authority", "licensee",
            "asset_version", "use", "jurisdiction", "term", "modification", "sublicense")}
        with self.assertRaisesRegex(ValueError, "LICENSE_TERM_INVALID"):
            self.license([license_material["event_id"]], [fact["event_id"]], coverage=coverage,
                         overall_coverage="covered", relationship_event_id=relation["event_id"],
                         license_start="2027-01-01")
        row = self.license([license_material["event_id"]], [fact["event_id"]], coverage=coverage,
                           overall_coverage="covered", relationship_event_id=relation["event_id"],
                           license_start="2026-01-01", license_end="2026-12-31")
        self.assertEqual(row["overall_coverage"], "covered")
        self.assertIn("M07_CLOSE_PENDING", self.fx.blockers())

    def test_changed_source_fact_pauses_copyright_review_chain(self):
        material, fact = self.copyright()
        source = self.source(material, fact)
        self.relationship(source, [material["event_id"]], [fact["event_id"]])
        self.fx.add("impact", impact_reasoning="Archived page changed after source review",
                    affected_fact_event_ids=[fact["event_id"]], evidence_refs=["E1"])
        scope = self.fx.view()["scopes"][0]
        self.assertFalse(scope["substantive_reviews"]["copyright_source_currently_usable"])
        self.assertFalse(scope["substantive_reviews"]["copyright_relationship_currently_usable"])
        self.assertIn("M07_COPYRIGHT_RECHECK_PENDING", self.fx.blockers())
        with self.assertRaisesRegex(ValueError, "AFFECTED_FACT_UNUSABLE"):
            self.relationship(source, [material["event_id"]], [fact["event_id"]])


if __name__ == "__main__":
    unittest.main()
