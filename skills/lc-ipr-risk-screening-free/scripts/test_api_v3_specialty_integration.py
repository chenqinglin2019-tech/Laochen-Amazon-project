"""Offline API adapter -> retained receipt -> specialty material/fact contracts."""
import copy
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from common import (AUTOMATION_POLICY_REVISION, active_free_policy, atomic_write_json,
                    now_iso, sha256_file, sha256_json, signa_free_enhancement, serpapi_free_enhancement)
from provider_utils import ProviderError, authorize_exact_plan_execution
import euipo_client
import jpo_api_client
import serpapi_patent_details_client as details
import signa_client
import test_specialty_analysis as m06_fixture
import test_distinctive_rights as m07_fixture
from test_api_v3_provider_records import mark_record, signa_item
import trusted_api


class SpecialtyApiIntegrationTests(unittest.TestCase):
    def test_generated_signa_detail_reaches_request_boundary_with_real_authorization(self):
        from candidate_api_actions import append
        from common import serper_free_enhancement
        from decision_workflow import effective_selected_candidates
        from coverage_v3 import build_requirements
        from workflow_v24 import build_coverage_requirements_v24
        f = self.fixture(trademark=True)
        f.task.update(free_policy=active_free_policy(), free_policy_revision=AUTOMATION_POLICY_REVISION,
            retrieval_policy={"enabled": True},
            product_delivery_revision="image-fact-v1",
            signa_free_enhancement=signa_free_enhancement(True),
            serper_free_enhancement=serper_free_enhancement(False, trusted_api.REVISION),
            serpapi_free_enhancement=serpapi_free_enhancement(False, trusted_api.REVISION))
        f.task["coverage_requirements"] = build_requirements(f.task, build_coverage_requirements_v24(
            f.task["target_jurisdictions"], screening_revision=f.task.get("screening_revision"),
            specialty_workflow_revision=f.task.get("specialty_workflow_revision")))
        f.evidence.update(task_id=f.task["task_id"], schema_version=f.task["schema_version"])
        f.save()
        decision = effective_selected_candidates(f.task, f.candidates, f.ledger, evidence=f.evidence)[0]
        plan = {key: f.task[key] for key in ("schema_version", "task_id", "free_policy",
            "free_policy_revision", "decision_workflow_revision", "workflow_correction_revision",
            "retrieval_workflow_revision", "signa_free_enhancement", "serper_free_enhancement",
            "serpapi_free_enhancement", "retrieval_policy")}
        plan["queries"] = {}
        plan["retrieval_policy_sha256"] = sha256_json(f.task["retrieval_policy"])
        gaps = append(f.task, f.evidence, plan["queries"], f.candidate, decision, [],
            capabilities={"signa": {"executable": True}})
        self.assertEqual(gaps, [])
        row = plan["queries"]["signa"][0]
        self.assertIn("territory", row["missing_facts"])
        self.assertEqual(row["product_delivery_revision"], "image-fact-v1")
        self.assertEqual(row["product_fact_refs"], [])
        atomic_write_json(f.path / "search-plan.json", plan)
        # Keep both plan and scenario authorization real; stop at the request
        # boundary because this regression must not consume API credits.
        with patch.object(signa_client, "_execute_known_record", return_value={"status": "boundary"}) as request:
            self.assertEqual(signa_client.execute(f.path, row["query_id"]), {"status": "boundary"})
        request.assert_called_once()

    def fixture(self, trademark=False):
        value = m07_fixture.DistinctiveRightsTests() if trademark else m06_fixture.SpecialtyAnalysisTests()
        if trademark:
            from test_decision_workflow import DecisionWorkflowTests
            original = DecisionWorkflowTests.use_trademark
            def real_mark_identity(fixture):
                original(fixture)
                fixture.candidate.pop("publication_number", None)
                fixture.candidate.update(provider_record_id="tm_fixture", serial_number="12345678",
                                         normalization_key="tm_fixture")
            with patch.object(DecisionWorkflowTests, "use_trademark", real_mark_identity):
                value.setUp()
        else:
            value.setUp()
        self.addCleanup(value.doCleanups)
        value.task["retrieval_workflow_revision"] = trusted_api.REVISION
        value.save()
        value.intake()
        return value

    def retain(self, fixture, normalized, *, provider="serpapi_google_patents", checked_at=None, jurisdiction="US", operation="candidate_detail", evidence_id="API-E"):
        """Persist synthetic offline adapter output with the real receipt annotator."""
        raw = fixture.path / ("raw-api-fixture.json" if evidence_id == "API-E" else "raw-" + evidence_id + ".json")
        atomic_write_json(raw, normalized)
        shared = dict(provider=provider, operation=operation, query_id=evidence_id + "-Q",
                      jurisdiction=jurisdiction, right_type=fixture.scope()["right_type"], plan_entry_sha256=sha256_json({"fixture": True}))
        run = {**shared, "run_id": evidence_id + "-R", "status": "success", "error_code": "",
               "source_environment": "production", "finished_at": checked_at or now_iso(),
               "raw_paths": [str(raw)], "payload_digest": sha256_file(raw)}
        record = {**shared, "source_run_id": run["run_id"], "evidence_id": evidence_id, "payload": normalized}
        trusted_api.annotate_entry(fixture.task, record, run)
        fixture.evidence.setdefault("source_runs", []).append(run)
        fixture.evidence["collections"].setdefault("api_records", []).append(record)
        fixture.save()
        return record

    def patent(self, fixture, **changes):
        number = fixture.candidate["publication_number"]
        raw = {"publication_number": number, "claims": ["1. A strap having a hook."],
               "current_assignee": ["Current holder"], "current_status": "Active"}
        raw.update(changes)
        return details._normalize(raw, {"q": number, "patent_id": "patent/" + number + "/en",
            "candidate_id": "C1", "jurisdiction": "US", "right_type": "patent"}, retrieval_workflow_revision=trusted_api.REVISION)

    def material(self, fixture, **changes):
        request = dict(document_id=fixture.candidate["publication_number"], document_version="api-v1",
            evidence_refs=["API-E"], acquired_at=now_iso(), source_form=trusted_api.FORM,
            purposes=["identity", "territory", "status", "protection", "rights_holder"],
            reading_locations=["retained JSON: target record fields"], status="sufficient_for_listed_purposes",
            supported_facts=["identity", "territory", "status", "protection", "rights_holder"],
            support_reasoning="Read only the exact returned fields")
        request.update(changes)
        return fixture.add("material", **request)

    def test_m06_status_holder_and_claims_use_api_without_official_material(self):
        fixture = self.fixture()
        self.retain(fixture, self.patent(fixture))
        material = self.material(fixture)
        for kind in ("identity", "territory", "status", "rights_holder", "protection"):
            with self.subTest(kind=kind):
                fact = fixture.fact(kind, material, right_identity=fixture.candidate["publication_number"],
                                    source_checked_date=now_iso()[:10])
                self.assertEqual(fact["outcome"], "supported")
        accepted = trusted_api.accepted_verification(fixture.task, fixture.evidence, fixture.candidate, "US", "patent")
        self.assertTrue(accepted["complete"], accepted)

    def test_wrong_record_identity_rejects_material(self):
        fixture = self.fixture()
        self.retain(fixture, self.patent(fixture))
        with self.assertRaisesRegex(ValueError, "API_RECORD_IDENTITY_OR_RECEIPT_INVALID"):
            self.material(fixture, document_id="US99999999B2")

    def test_other_record_cannot_be_bound_to_canonical_candidate(self):
        fixture = self.fixture()
        row = self.patent(fixture)
        row["publication_number"] = "US99999999B2"
        self.retain(fixture, row)
        with self.assertRaisesRegex(ValueError, "API_RECORD_IDENTITY_OR_RECEIPT_INVALID"):
            self.material(fixture, document_id="US99999999B2",
                api_candidate_identity={"candidate_id": "C1", "publication_number": "US99999999B2"})

    def test_fact_identity_cannot_override_canonical_material(self):
        fixture = self.fixture()
        self.retain(fixture, self.patent(fixture))
        material = self.material(fixture)
        self.assertEqual(material["api_candidate_identity"]["publication_number"], fixture.candidate["publication_number"])
        with self.assertRaisesRegex(ValueError, "API_FACT_NOT_RETURNED"):
            fixture.fact("status", material, right_identity="US99999999B2")

    def test_tampered_raw_record_rejects_material(self):
        fixture = self.fixture()
        self.retain(fixture, self.patent(fixture))
        (fixture.path / "raw-api-fixture.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "API_RECORD_IDENTITY_OR_RECEIPT_INVALID"):
            self.material(fixture)

    def test_missing_claims_rejects_protection_fact(self):
        fixture = self.fixture()
        self.retain(fixture, self.patent(fixture, claims=[]))
        material = self.material(fixture)
        with self.assertRaisesRegex(ValueError, "API_FACT_NOT_RETURNED"):
            fixture.fact("protection", material)

    def test_truncated_claims_rejects_protection_fact(self):
        fixture = self.fixture()
        self.retain(fixture, self.patent(fixture, claims_truncated=True))
        material = self.material(fixture)
        with self.assertRaisesRegex(ValueError, "API_FACT_NOT_RETURNED"):
            fixture.fact("protection", material)

    def test_applicant_does_not_supply_holder_fact(self):
        fixture = self.fixture()
        self.retain(fixture, self.patent(fixture, current_assignee=[], assignees=["Original applicant"]))
        material = self.material(fixture)
        with self.assertRaisesRegex(ValueError, "API_FACT_NOT_RETURNED"):
            fixture.fact("rights_holder", material)

    def test_historical_grant_does_not_supply_current_status(self):
        fixture = self.fixture()
        self.retain(fixture, self.patent(fixture, current_status="", legal_events=[{"title": "Patent granted"}]))
        material = self.material(fixture)
        with self.assertRaisesRegex(ValueError, "API_FACT_NOT_RETURNED"):
            fixture.fact("status", material)

    def test_expired_dynamic_receipt_keeps_static_claims_only(self):
        fixture = self.fixture()
        old = (datetime.now(timezone.utc) - timedelta(hours=49)).isoformat()
        self.retain(fixture, self.patent(fixture), checked_at=old)
        material = self.material(fixture)
        self.assertEqual(fixture.fact("protection", material)["outcome"], "supported")
        with self.assertRaisesRegex(ValueError, "API_FACT_NOT_RETURNED"):
            fixture.fact("status", material)

    def mark_material(self, fixture, **changes):
        return fixture.material(document_id="tm_fixture", source_form=trusted_api.FORM,
                                acquired_at=now_iso(), evidence_refs=["API-E"], **changes)

    def test_m07_complete_signa_goods_are_accepted_without_official_material(self):
        fixture = self.fixture(trademark=True)
        normalized = signa_client.normalize_detail(mark_record(mark_feature_type="word"),
                    signa_item(right_type="trademark_word"))
        self.retain(fixture, normalized, provider="signa")
        material = self.mark_material(fixture)
        fact = fixture.fact("registration", material, api_fact="goods_services", right_identity="tm_fixture",
                            source_checked_at=now_iso())
        self.assertEqual(fact["outcome"], "supported")

    def test_m07_missing_or_truncated_goods_cannot_be_registered_fact(self):
        for value in ([], [{"nice_class": 20}], [{"nice_class": 20, "goods_services_text": "Furniture", "goods_services_text_truncated": True}]):
            with self.subTest(value=value):
                fixture = self.fixture(trademark=True)
                normalized = signa_client.normalize_detail(mark_record(mark_feature_type="word", classifications=value),
                            signa_item(right_type="trademark_word"))
                self.retain(fixture, normalized, provider="signa")
                material = self.mark_material(fixture)
                with self.assertRaisesRegex(ValueError, "REGISTRATION_OFFICIAL_BASIS_REQUIRED"):
                    fixture.fact("registration", material, api_fact="goods_services", right_identity="tm_fixture", source_checked_at=now_iso())

    def test_m07_wrong_record_identity_rejects_material(self):
        fixture = self.fixture(trademark=True)
        normalized = signa_client.normalize_detail(mark_record(mark_feature_type="word"), signa_item(right_type="trademark_word"))
        self.retain(fixture, normalized, provider="signa")
        with self.assertRaisesRegex(ValueError, "API_RECORD_IDENTITY_OR_RECEIPT_INVALID"):
            fixture.material(document_id="tm_wrong", source_form=trusted_api.FORM, evidence_refs=["API-E"])

    def test_m07_fact_identity_cannot_override_canonical_mark(self):
        fixture = self.fixture(trademark=True)
        normalized = signa_client.normalize_detail(mark_record(mark_feature_type="word"), signa_item(right_type="trademark_word"))
        self.retain(fixture, normalized, provider="signa")
        material = self.mark_material(fixture)
        with self.assertRaisesRegex(ValueError, "REGISTRATION_OFFICIAL_BASIS_REQUIRED"):
            fixture.fact("registration", material, api_fact="goods_services", right_identity="tm_wrong", source_checked_at=now_iso())

    def test_legacy_specialty_does_not_accept_new_source_form(self):
        fixture = self.fixture()
        self.retain(fixture, self.patent(fixture))
        fixture.task["retrieval_workflow_revision"] = "api-first-v2"
        fixture.save()
        with self.assertRaisesRegex(ValueError, "SPECIALTY_MATERIAL_INVALID"):
            self.material(fixture)

    def test_test_fixture_environment_cannot_support_material(self):
        fixture = self.fixture()
        entry = self.retain(fixture, self.patent(fixture))
        run = fixture.evidence["source_runs"][-1]
        run["source_environment"] = "test_fixture"
        trusted_api.annotate_entry(fixture.task, entry, run)
        fixture.save()
        with self.assertRaisesRegex(ValueError, "API_RECORD_IDENTITY_OR_RECEIPT_INVALID"):
            self.material(fixture)

    def test_cross_national_status_never_supports_target_record(self):
        fixture = self.fixture()
        row = self.patent(fixture)
        row.update(jurisdiction="GB", current_status="Active")
        self.retain(fixture, row)
        with self.assertRaisesRegex(ValueError, "API_RECORD_IDENTITY_OR_RECEIPT_INVALID"):
            self.material(fixture)
        result = trusted_api.accepted_candidate_facts(fixture.task, fixture.evidence, fixture.candidate, "US", "patent")
        self.assertNotIn("current_status", result)

    def test_ep_document_static_fields_do_not_replace_national_status(self):
        fixture = self.fixture()
        raw = {"publication_number": "EP1234567B1", "claims": ["1. A strap having a hook."],
               "current_status": "Active", "current_assignee": ["EP holder"]}
        row = details._normalize(raw, {"q": "EP1234567B1", "patent_id": "patent/EP1234567B1/en",
            "candidate_id": "C1", "jurisdiction": "EP", "right_type": "patent"}, retrieval_workflow_revision=trusted_api.REVISION)
        self.retain(fixture, row, jurisdiction="EP")
        for target in ("GB", "DE", "FR", "IT", "ES", "EU"):
            with self.subTest(target=target):
                candidate = {"publication_number": "EP1234567B1", "jurisdiction": target, "right_type": "patent"}
                facts = trusted_api.accepted_candidate_facts(fixture.task, fixture.evidence, candidate)
                self.assertEqual(set(facts), {"identity", "protection_content"})
        for target in ("US", "JP"):
            with self.subTest(target=target):
                candidate = {"publication_number": "EP1234567B1", "jurisdiction": target, "right_type": "patent"}
                self.assertFalse(trusted_api.accepted_candidate_facts(fixture.task, fixture.evidence, candidate))

    def test_frozen_material_fact_reuses_assessment_instant(self):
        import final_review
        fixture = self.fixture()
        entry = self.retain(fixture, self.patent(fixture))
        material = self.material(fixture)
        fixture.task["review_policy_revision"] = final_review.REVISION
        at = now_iso()
        fixture.task["final_review_freeze"] = final_review.freeze_time_binding(fixture.task, fixture.evidence, at)
        later = (datetime.now(timezone.utc) + timedelta(hours=72)).isoformat()
        with patch.object(final_review, "now_iso", return_value=later):
            self.assertTrue(trusted_api.material_fact(fixture.task, material, {"API-E": entry}, "status", evidence=fixture.evidence))
            changed = copy.deepcopy(fixture.evidence)
            changed["collections"]["api_records"][0]["payload"]["current_status"] = "Expired"
            self.assertFalse(trusted_api.material_fact(fixture.task, material, {"API-E": entry}, "status", evidence=changed))

    def test_record_fact_passes_evidence_to_frozen_time_check(self):
        import final_review
        fixture = self.fixture()
        self.retain(fixture, self.patent(fixture))
        material = self.material(fixture)
        fixture.task["review_policy_revision"] = final_review.REVISION
        fixture.task["final_review_freeze"] = final_review.freeze_time_binding(fixture.task, fixture.evidence)
        fixture.save()
        later = (datetime.now(timezone.utc) + timedelta(hours=72)).isoformat()
        with patch.object(final_review, "now_iso", return_value=later):
            fact = fixture.fact("status", material, right_identity=fixture.candidate["publication_number"])
        self.assertEqual(fact["outcome"], "supported")


class PublicApiIntegrationTests(unittest.TestCase):
    URL = "https://example.test/works/original-design"

    def fixture(self, right="unregistered_design", **content):
        import decision_workflow
        from candidate_triage_stage import record_selected_handoff
        helper = SpecialtyApiIntegrationTests()
        f = m06_fixture.SpecialtyAnalysisTests() if right == "unregistered_design" else m07_fixture.DistinctiveRightsTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        f.candidate.pop("publication_number", None)
        f.candidate.update(right_type=right, url=self.URL, normalization_key=self.URL)
        collection = "patents" if right == "unregistered_design" else "copyright_assets"
        f.candidates = {collection: [f.candidate]}
        f.task.update(retrieval_workflow_revision=trusted_api.REVISION, candidate_triage_stage_events=[])
        f.task["product_scope"].update(objects=[{"object_id": "public-object", "kind": "pattern", "relation": "integrated",
            "scope_status": "included", "right_types": [right]}], directions=[{"direction_id": "public-use",
            "scenario_id": "product_entry", "right_type": right, "object_ids": ["public-object"], "fact_ids": []}],
            candidate_links=[{"candidate_id": "C1", "object_ids": ["public-object"], "source_refs": ["E1"], "reason": "Exact public work"}])
        f.ledger["annotations"] = []
        f.scope = lambda: {"candidate_id": "C1", "scenario_id": "product_entry", "jurisdiction": "US", "right_type": right}
        annotation = decision_workflow.make_annotation(f.task, collection, f.candidate, {
            "annotation_id": "PUBLIC-D", "scenario_id": "product_entry", "decision": "selected", "reviewer": "offline",
            "annotated_at": now_iso(), "reason": "Actual public work", "basis_summary": "Exact work identity",
            "reading_level": "result_record", "evidence_refs": ["E1"], "reopen_conditions": ["Changed work"],
            "candidate_relation": {"product_object_ids": ["public-object"], "direction_ids": ["public-use"],
                "scope_reason": "Artwork used on product", "evidence_refs": ["E1"], "identity_gaps": []},
            "comparison": {"candidate_content": "Public pattern", "product_content": "Pattern used on product",
                "relationship": "Same pattern", "investigation_question": "Applicable rights in this work?"}}, evidence=f.evidence)
        f.ledger["annotations"].append(annotation)
        f.save()
        f.handoff_id = record_selected_handoff(f.path, {**f.scope(), "annotation_id": annotation["annotation_id"],
            "evidence_refs": ["E1"], "reading_scope": {"level": "result_record", "sections": ["public work"]},
            "verification_gaps": [], "reviewer": "offline", "reason": "Review exact source work"})["event_id"]
        f.refresh()
        if right == "unregistered_design":
            f.intake()
        else:
            f.object_id = "public-object"
            f.intake(tracks={"registration": {"needed": False, "reasoning": "Public source analysis"},
                             "public_facts": {"needed": True, "reasoning": "Review public content"}})
        row = {"url": self.URL, "title": "Public pattern", "snippet": "Search excerpt", **content}
        helper.retain(f, row, provider="serper_web", operation="search")
        return f

    def material(self, f, *, document=None, facts=None, evidence_refs=None):
        values = {"document_id": document or self.URL, "document_version": "public-v1", "evidence_refs": evidence_refs or ["API-E"],
            "acquired_at": now_iso(), "source_form": trusted_api.FORM, "reading_locations": ["Returned public content"],
            "support_reasoning": "Read actual returned scope"}
        if f.scope()["right_type"] == "unregistered_design":
            values.update(purposes=facts or ["identity", "protection"], supported_facts=facts or ["identity", "protection"], status="sufficient_for_listed_purposes")
        else:
            values.update(tracks=["public_facts"], status="sufficient_for_listed_tracks")
        return f.add("material", **values)

    def rule(self, f):
        return f.add("material", document_id="RULE-1", document_version="rule-v1", evidence_refs=["E1"], acquired_at=now_iso(),
            source_form="legal_rule", purposes=["legal_conditions"], supported_facts=["legal_conditions"],
            reading_locations=["Applicable rule section"], status="sufficient_for_listed_purposes", support_reasoning="Read applicability conditions")

    def conditions(self, f, material, rule, *, outcome="supported"):
        return f.add("fact", fact_id="RULE-FACT", fact_kind="legal_conditions", outcome="supported",
            raw_statement="Applicable rule and public disclosure facts", reasoning="Read applicable conditions",
            document_version="public-v1", reading_locations=["Rule and disclosure"], evidence_refs=["E1", "API-E"],
            material_event_ids=[material["event_id"], rule["event_id"]], rules_basis="Applicable jurisdictional rule",
            conditions=[{"condition_id": "disclosure", "outcome": outcome, "applicability_reasoning": "Exact design disclosed",
                "evidence_refs": ["API-E"], "design_version": "public-v1", "disclosed_content": "Original pattern",
                "date_basis": "Returned publication date and content", "geographic_basis": "Disclosed place assessed under rule"}])

    def infer(self, f, material, rule, conditions, **changes):
        values = dict(fact_id="INFERENCE", fact_kind="status", outcome="supported", raw_statement="Bounded rule-based conclusion",
            reasoning="Public facts applied to the stated rule", inference_reasoning="All recorded conditions are supported",
            legal_conditions_event_id=conditions["event_id"], document_version="public-v1", reading_locations=["Rule and work"],
            evidence_refs=["E1", "API-E"], material_event_ids=[material["event_id"], rule["event_id"]],
            right_identity=self.URL, territory_basis="Applicable rule territory", source_checked_date=now_iso()[:10])
        values.update(changes)
        return f.add("fact", **values)

    def test_unregistered_design_uses_public_content_and_rule_without_register(self):
        f = self.fixture(full_text="Complete disclosure of this design.", publication_date="2026-01-01")
        material, rule = self.material(f), self.rule(f)
        self.assertIn("original_content", material["api_public_content_scope"])
        for kind in ("identity", "protection"):
            self.assertEqual(f.fact(kind, material)["outcome"], "supported")
        conditions = self.conditions(f, material, rule)
        for kind in ("status", "territory"):
            result = self.infer(f, material, rule, conditions, fact_kind=kind, fact_id="INFER-" + kind)
            self.assertEqual(result["analysis_basis"], "public_facts_with_applicable_rule")

    def test_public_summary_does_not_become_full_design_material(self):
        f = self.fixture()
        with self.assertRaisesRegex(ValueError, "PUBLIC_ORIGINAL_CONTENT_REQUIRED"):
            self.material(f)
        material = self.material(f, facts=["identity"])
        self.assertEqual(material["api_public_content_scope"], ["public_identity", "source_excerpt"])

    def test_wrong_public_work_cannot_be_attached_to_selected_candidate(self):
        f = self.fixture("copyright", url="https://example.test/works/other", full_text="Other work")
        with self.assertRaisesRegex(ValueError, "API_RECORD_IDENTITY_OR_RECEIPT_INVALID"):
            self.material(f, document="https://example.test/works/other")

    def test_unregistered_status_without_legal_rule_is_rejected(self):
        f = self.fixture(full_text="Complete disclosure")
        material = self.material(f)
        with self.assertRaisesRegex(ValueError, "PUBLIC_RULE_BASIS_REQUIRED"):
            f.fact("status", material, right_identity=self.URL, resolves_handoff_gaps=[])

    def test_unknown_or_missing_condition_basis_cannot_support_status(self):
        f = self.fixture(full_text="Complete disclosure")
        material, rule = self.material(f), self.rule(f)
        conditions = self.conditions(f, material, rule, outcome="unknown")
        for changes in ({}, {"legal_conditions_event_id": "wrong"}):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, "INFERENCE_BASIS_REQUIRED"):
                self.infer(f, material, rule, conditions, **changes)

    def test_copyright_and_trade_dress_public_api_facts_are_scoped(self):
        for right in ("copyright", "trade_dress"):
            with self.subTest(right=right):
                f = self.fixture(right, full_text="Complete public work", publication_date="2026-01-01")
                material = self.material(f)
                fact = f.fact("public_facts", material, api_fact="original_content")
                self.assertEqual(fact["outcome"], "supported")
                with self.assertRaisesRegex(ValueError, "PUBLIC_API_FACT_NOT_RETURNED"):
                    f.fact("public_facts", material, api_fact="current_status")
                with self.assertRaisesRegex(ValueError, "PUBLIC_API_FACT_NOT_RETURNED"):
                    f.fact("public_facts", material, api_fact="original_content", right_identity="https://example.test/other")

    def test_excerpt_can_be_read_but_cannot_be_claimed_as_full_copyright(self):
        f = self.fixture("copyright")
        material = self.material(f)
        self.assertEqual(f.fact("public_facts", material, api_fact="source_excerpt")["outcome"], "supported")
        with self.assertRaisesRegex(ValueError, "PUBLIC_API_FACT_NOT_RETURNED"):
            f.fact("public_facts", material, api_fact="original_content")

    def test_copyright_source_accepts_original_api_content_only(self):
        for original in (True, False):
            with self.subTest(original=original):
                f = self.fixture("copyright", **({"full_text": "Complete public work"} if original else {}))
                material = self.material(f)
                fact = f.fact("public_facts", material, api_fact="original_content" if original else "source_excerpt")
                request = dict(material_event_ids=[material["event_id"]], fact_event_ids=[fact["event_id"]],
                    evidence_refs=["API-E"], intended_asset_version="logo-v1", source_work_id=self.URL,
                    source_work_version="public-v1", actually_reviewed_content="Returned work content",
                    content_location="API returned text", version_correspondence_reasoning="Exact URL and retained content", time_points=[])
                if original:
                    self.assertEqual(f.add("copyright_source", **request)["source_work_id"], self.URL)
                else:
                    with self.assertRaisesRegex(ValueError, "COPYRIGHT_ORIGINAL_REQUIRED"):
                        f.add("copyright_source", **request)

    def test_public_inference_rejects_wrong_work_and_superseded_conditions(self):
        f = self.fixture(full_text="Complete disclosure")
        material, rule = self.material(f), self.rule(f)
        conditions = self.conditions(f, material, rule)
        with self.assertRaisesRegex(ValueError, "INFERENCE_BASIS_REQUIRED"):
            self.infer(f, material, rule, conditions, right_identity="https://example.test/other")
        self.conditions(f, material, rule, outcome="unknown")
        with self.assertRaisesRegex(ValueError, "INFERENCE_BASIS_REQUIRED"):
            self.infer(f, material, rule, conditions)

    def test_thumbnail_does_not_supply_original_work(self):
        from PIL import Image
        f = self.fixture("copyright")
        path = f.path / "thumbnail.png"
        Image.new("RGB", (2, 2)).save(path)
        entry = f.evidence["collections"]["api_records"][0]
        entry["payload"]["media"] = [{"path": str(path), "sha256": sha256_file(path), "role": "thumbnail"}]
        raw = f.path / "raw-api-fixture.json"
        atomic_write_json(raw, entry["payload"])
        run = f.evidence["source_runs"][-1]
        run["payload_digest"] = sha256_file(raw)
        trusted_api.annotate_entry(f.task, entry, run)
        f.save()
        material = self.material(f)
        with self.assertRaisesRegex(ValueError, "PUBLIC_API_FACT_NOT_RETURNED"):
            f.fact("public_facts", material, api_fact="original_content")
        entry["payload"]["media"][0]["role"] = "original_work"
        atomic_write_json(raw, entry["payload"])
        run["payload_digest"] = sha256_file(raw)
        trusted_api.annotate_entry(f.task, entry, run)
        f.save()
        material = self.material(f)
        self.assertEqual(f.fact("public_facts", material, api_fact="original_content")["outcome"], "supported")

    def test_truncated_text_and_null_media_metadata_are_handled(self):
        for truncated in (True, False):
            with self.subTest(truncated=truncated):
                f = self.fixture("copyright", full_text="Returned text", full_text_truncated=truncated,
                                 media_acquisition=None, publication_date="unknown")
                material = self.material(f)
                self.assertNotIn("disclosure", material["api_public_content_scope"])
                if truncated:
                    with self.assertRaisesRegex(ValueError, "PUBLIC_API_FACT_NOT_RETURNED"):
                        f.fact("public_facts", material, api_fact="original_content")
                else:
                    self.assertEqual(f.fact("public_facts", material, api_fact="original_content")["outcome"], "supported")

    def test_copyright_relationship_requires_actual_complete_work_and_chain_reasoning(self):
        import distinctive_rights
        for complete in (True, False):
            with self.subTest(complete=complete):
                f = self.fixture("copyright", full_text="Complete original work with explicit rights statement")
                material = self.material(f)
                fact = f.fact("public_facts", material, api_fact="original_content")
                source = f.add("copyright_source", material_event_ids=[material["event_id"]], fact_event_ids=[fact["event_id"]],
                    evidence_refs=["API-E"], intended_asset_version="logo-v1", source_work_id=self.URL,
                    source_work_version="public-v1", actually_reviewed_content="Returned original work",
                    content_location="Full returned text", version_correspondence_reasoning="Exact canonical work", time_points=[])
                ref = "API-E"
                if not complete:
                    SpecialtyApiIntegrationTests().retain(f, {"url": self.URL, "snippet": "Rights summary only"},
                        provider="serper_web", operation="search", evidence_id="API-S")
                    material = self.material(f, evidence_refs=["API-S"])
                    fact = f.fact("public_facts", material, api_fact="source_excerpt")
                    ref = "API-S"
                unknown = {"outcome": "unknown", "reasoning": "Not decided by this fact", "dependency_or_basis": "Separate inquiry", "evidence_refs": [ref]}
                parties = {name: copy.deepcopy(unknown) for name in distinctive_rights.COPYRIGHT_PARTIES}
                for name in ("owner", "licensor"):
                    parties[name] = {"outcome": "supported", "reasoning": "Read the explicit documented chain", "evidence_refs": [ref],
                                     "identity": "Named party", "relationship_basis": "Explicit rights statement for this work"}
                params = dict(source_event_id=source["event_id"], material_event_ids=[material["event_id"]],
                    fact_event_ids=[fact["event_id"]], evidence_refs=[ref], parties=parties,
                    questions={name: copy.deepcopy(unknown) for name in distinctive_rights.COPYRIGHT_QUESTIONS})
                if complete:
                    self.assertEqual(f.add("copyright_relationship", **params)["parties"]["owner"]["outcome"], "supported")
                    parties["owner"]["relationship_basis"] = ""
                    with self.assertRaisesRegex(ValueError, "IDENTITY_BASIS_REQUIRED"):
                        f.add("copyright_relationship", **params)
                else:
                    with self.assertRaisesRegex(ValueError, "RIGHTS_CHAIN_REQUIRED"):
                        f.add("copyright_relationship", **params)

    def test_trade_dress_regime_requires_full_rule_body(self):
        for complete in (True, False):
            with self.subTest(complete=complete):
                f = self.fixture("trade_dress", **({"full_text": "Complete applicable trade dress rule"} if complete else {}))
                material = self.material(f)
                fact = f.fact("public_facts", material, api_fact="original_content" if complete else "source_excerpt")
                intake = next(row for row in reversed(f.task["distinctive_rights_events"]) if row["kind"] == "intake")
                claim = f.add("trade_dress_claim", appearance_version=intake["subject_version"],
                    product_version_sha256=intake["product_version_sha256"], use_context=intake["use_context"],
                    claimed_object_id=intake["object_id"], boundary_status="defined", boundary_reasoning="Reviewed visual boundary",
                    features=[{"feature_id": "P1", "kind": "shape", "appearance_version": intake["subject_version"],
                               "description": "Defined visual contour", "evidence_refs": ["API-E"]}],
                    combination_relation="One complete contour", evidence_refs=["API-E"])
                request = dict(claim_event_id=claim["event_id"], regime="us_trade_dress", basis_status="reviewed",
                    legal_basis_or_gap="Full applicable rule read", conditions=[{"condition_id": "source_identity", "question": "Source identifying use?",
                    "review": {"outcome": "unknown", "reasoning": "Apply after factual use review", "dependency_or_basis": "Use evidence needed", "evidence_refs": ["API-E"]}}],
                    material_event_ids=[material["event_id"]], fact_event_ids=[fact["event_id"]], evidence_refs=["API-E"])
                if complete:
                    self.assertEqual(f.add("trade_dress_regime", **request)["basis_status"], "reviewed")
                else:
                    with self.assertRaisesRegex(ValueError, "RULE_SOURCE_REQUIRED"):
                        f.add("trade_dress_regime", **request)


class CandidateApiBudgetTests(unittest.TestCase):
    def task(self):
        return {"retrieval_workflow_revision": trusted_api.REVISION,
                "signa_free_enhancement": signa_free_enhancement(True),
                "serpapi_free_enhancement": serpapi_free_enhancement(True, trusted_api.REVISION)}

    def test_full_signa_plan_is_preserved_and_gap_is_bounded(self):
        import candidate_api_actions as actions
        maximum = self.task()["signa_free_enhancement"]["max_queries_per_task"]
        queries = {"signa": [{"query_id": "Q" + str(index)} for index in range(maximum)]}
        original = copy.deepcopy(queries)
        candidate = {"candidate_id": "C1", "provider_record_id": "tm_fixture", "right_type": "trademark_word", "jurisdiction": "US"}
        decision = {**candidate, "scenario_id": "product_entry"}
        gaps = actions.append(self.task(), {"source_runs": [], "collections": {}}, queries,
            candidate, decision, [], capabilities={"signa": {"executable": True}})
        self.assertEqual(queries, original)
        self.assertEqual(gaps[0]["api_budget_limits"], {"signa": "FREE_TASK_PLAN_LIMIT_REACHED"})

    def test_patents_and_lens_share_planned_slots(self):
        from candidate_api_actions import _budget_issue
        maximum = self.task()["serpapi_free_enhancement"]["max_queries_per_task"]
        queries = {"serpapi_google_patents": [{"query_id": "Q" + str(index)} for index in range(maximum - 1)],
                   "serpapi_google_lens": [{"query_id": "Q-lens"}]}
        self.assertEqual(_budget_issue(self.task(), {"source_runs": []}, queries, "serpapi_google_patents"), "FREE_TASK_PLAN_LIMIT_REACHED")

    def test_retries_and_pending_work_reserve_shared_actual_budget(self):
        from candidate_api_actions import _budget_issue
        maximum = self.task()["serpapi_free_enhancement"]["max_queries_per_task"]
        runs = [{"provider": "serpapi_google_patents", "operation": "candidate_detail", "query_id": "Q1",
                 "quota": {"network_request_attempted": True}} for _ in range(maximum - 1)]
        queries = {"serpapi_google_patents": [{"query_id": "Q1"}, {"query_id": "Q2"}]}
        self.assertEqual(_budget_issue(self.task(), {"source_runs": runs}, queries, "serpapi_google_patents"), "FREE_TASK_RESERVED_REQUEST_LIMIT_REACHED")
        runs.append(copy.deepcopy(runs[0]))
        self.assertEqual(_budget_issue(self.task(), {"source_runs": runs}, {}, "serpapi_google_patents"), "FREE_TASK_REQUEST_LIMIT_REACHED")

    def test_no_submission_does_not_consume_actual_request(self):
        from candidate_api_actions import _budget_issue
        run = {"provider": "signa", "operation": "candidate_detail", "query_id": "Q1",
               "quota": {"network_request_attempted": False, "search_request_attempted": False}}
        self.assertEqual(_budget_issue(self.task(), {"source_runs": [run]}, {"signa": [{"query_id": "Q1"}]}, "signa"), "")

    def test_recorded_quota_stop_prevents_additional_action(self):
        from candidate_api_actions import _budget_issue
        run = {"provider": "serpapi_google_lens", "operation": "image_search", "error_code": "FREE_QUOTA_EXHAUSTED"}
        self.assertEqual(_budget_issue(self.task(), {"source_runs": [run]}, {}, "serpapi_google_patents"), "FREE_PROVIDER_STOP_RECORDED")


class ExactProviderPlanIntegrationTests(unittest.TestCase):
    def fixture(self, provider, number, country, right, params):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name)
        task = {"schema_version": "2.4-free", "task_id": "offline-integration",
                "retrieval_workflow_revision": trusted_api.REVISION,
                "free_policy_revision": AUTOMATION_POLICY_REVISION, "free_policy": active_free_policy(),
                "target_jurisdictions": [country], "serpapi_free_enhancement": {"max_queries_per_task": 3}}
        row = {**params, "q": number, "candidate_id": "C1", "query_id": "API-Q", "jurisdiction": country,
               "right_type": right, "operation": "candidate_detail" if provider == "serpapi_google_patents" else "candidate_verification",
               "requirement_ids": ["fixture-record"], "missing_facts": ["rights_holder"],
               "api_gap_revision": trusted_api.REVISION, "gap_reason": "Missing current holder", "judgment_impact": "Holder analysis"}
        plan = {key: copy.deepcopy(task[key]) for key in ("schema_version", "task_id", "free_policy_revision", "free_policy")}
        plan["queries"] = {provider: [row]}
        for name, value in (("task", task), ("search-plan", plan), ("evidence", {"source_runs": []})):
            atomic_write_json(path / (name + ".json"), value)
        return path, task, row, plan

    def recorder(self, task, calls):
        def record(path, **values):
            authorize_exact_plan_execution(path, task, values["provider"], values["operation"], values["query_id"],
                jurisdiction=values["jurisdiction"], right_type=values["request_params"]["right_type"],
                query=values["query"], request_params=values["request_params"])
            calls.append(values)
            return {"status": "success" if "error_value" not in values else "failed", "run_id": "API-R"}
        return record

    def test_euipo_success_and_failure_preserve_exact_missing_facts(self):
        for failure in (False, True):
            with self.subTest(failure=failure):
                path, task, row, _ = self.fixture("euipo_trademark", "012345", "EU", "trademark_word", {"identifier": "012345", "detail": True})
                argv = ["euipo_client.py", "--task-dir", str(path), "trademark", "--query", "012345", "--verify", "--identifier", "012345", "--candidate-id", "C1", "--query-id", "API-Q"]
                calls = []
                result = ({"applicationNumber": "012345", "status": "Registered", "owners": [{"name": "Holder"}]}, {}, b"{}")
                with patch("sys.argv", argv), patch("sys.stdout", io.StringIO()), patch.object(euipo_client, "assert_provider_execution_allowed"), patch.object(euipo_client, "source_profile", return_value=("production", True)), patch.object(euipo_client, "api_get", side_effect=ProviderError("NETWORK_FAILED", "failed", "offline error") if failure else None, return_value=result), patch.object(euipo_client, "record_result", side_effect=self.recorder(task, calls)), patch.object(euipo_client, "record_error", side_effect=self.recorder(task, calls)):
                    euipo_client.main()
                self.assertEqual(calls[0]["request_params"]["missing_facts"], row["missing_facts"])

    def test_jpo_success_and_failure_preserve_exact_missing_facts(self):
        for failure in (False, True):
            with self.subTest(failure=failure):
                path, task, row, _ = self.fixture("jpo_api", "2020123456", "JP", "patent", {"number": "2020123456", "number_kind": "application"})
                argv = ["jpo_api_client.py", "--task-dir", str(path), "--right-type", "patent", "--number", "2020123456", "--candidate-id", "C1", "--query-id", "API-Q"]
                calls = []
                with patch("sys.argv", argv), patch("sys.stdout", io.StringIO()), patch.object(jpo_api_client, "assert_provider_execution_allowed"), patch.object(jpo_api_client, "JpoApiClient") as client, patch.object(jpo_api_client, "record_result", side_effect=self.recorder(task, calls)), patch.object(jpo_api_client, "record_error", side_effect=self.recorder(task, calls)):
                    client.return_value.source_environment = "production"
                    client.return_value.authoritative_for_final_rating = True
                    client.return_value.verify.return_value = ({"owners": ["Holder"]}, {}, b"{}", True, "")
                    if failure:
                        client.return_value.verify.side_effect = ProviderError("NETWORK_FAILED", "failed", "offline error")
                    jpo_api_client.main()
                self.assertEqual(calls[0]["request_params"]["missing_facts"], row["missing_facts"])

    def test_details_rejects_plan_parameter_drift_before_account_or_query(self):
        path, _, _, _ = self.fixture("serpapi_google_patents", "US11111111B2", "US", "patent",
            {"patent_id": "patent/US11111111B2/en", "unexpected_parameter": "must-reject"})
        with patch.object(details, "provider_execution_error", return_value=None), patch.object(details, "settings") as account, patch.object(details, "http_json") as network:
            with self.assertRaisesRegex(ProviderError, "parameter 'unexpected_parameter'"):
                details.execute(path, "API-Q")
        account.assert_not_called()
        network.assert_not_called()

    def test_details_rechecks_current_scenario_before_any_network(self):
        path, _, _, _ = self.fixture("serpapi_google_patents", "US11111111B2", "US", "patent", {"patent_id": "patent/US11111111B2/en"})
        with patch.object(details, "provider_execution_error", return_value=None), patch("provider_utils.authorize_current_scenario_action", side_effect=ProviderError("SCENARIO_ACTION_BLOCKED", "failed", "Changed decision")), patch.object(details, "settings") as account, patch.object(details, "http_json") as network:
            with self.assertRaisesRegex(ProviderError, "Changed decision"):
                details.execute(path, "API-Q")
        account.assert_not_called()
        network.assert_not_called()

    def test_details_failure_retains_request_scope_and_attempt(self):
        path, task, row, _ = self.fixture("serpapi_google_patents", "US11111111B2", "US", "patent", {"patent_id": "patent/US11111111B2/en"})
        calls = []
        with patch.object(details, "provider_execution_error", return_value=None), patch.object(details, "settings", return_value=({"http": {"timeout_seconds": 1}}, "https://serpapi.com", "offline-key")), patch.object(details, "free_account_snapshot", return_value={"plan_searches_left": 3}), patch.object(details, "reserve_search", return_value={}), patch.object(details, "http_json", side_effect=ProviderError("NETWORK_FAILED", "failed", "offline error")), patch.object(details, "record_result", side_effect=self.recorder(task, calls)):
            details.execute(path, "API-Q")
        self.assertEqual(calls[0]["request_params"]["missing_facts"], row["missing_facts"])
        self.assertEqual(calls[0]["request_params"]["right_type"], "patent")
        self.assertTrue(calls[0]["quota"]["network_request_attempted"])


if __name__ == "__main__":
    unittest.main()
