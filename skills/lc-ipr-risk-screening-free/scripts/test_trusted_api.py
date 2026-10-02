"""V3 fact adoption and bounded follow-ups, using retained offline records."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

from common import now_iso, sha256_file, sha256_json
import test_final_api_acceptance as fixtures
import trusted_api as api
import candidate_api_actions as actions


class TrustedApiTests(unittest.TestCase):
    setUp = fixtures.FinalApiAcceptanceTests.setUp
    tearDown = fixtures.FinalApiAcceptanceTests.tearDown
    refresh = fixtures.FinalApiAcceptanceTests.refresh

    def facts(self):
        return api.accepted_candidate_facts(self.task, self.evidence, self.candidate)

    def test_payload_or_original_change_invalidates_acceptance(self):
        self.assertIn("current_status", self.facts())
        self.entry["payload"]["extra"] = "tampered"
        self.assertEqual(self.facts(), {})
        self.refresh()
        self.raw.write_text("changed bytes")
        self.assertEqual(self.facts(), {})

    def test_conflicting_upstreams_leave_only_disputed_fact_open(self):
        other = deepcopy(self.entry)
        run = {**self.run, "run_id": "R2", "provider": "epo_ops"}
        other.update(evidence_id="E2", source_run_id="R2", provider="epo_ops")
        other["payload"]["records"][0]["current_status"] = "expired"
        api.annotate_entry(self.task, other, run)
        self.evidence["collections"]["patents"].append(other)
        self.evidence["source_runs"].append(run)
        self.assertNotIn("current_status", self.facts())
        self.assertIn("protection_content", self.facts())

    def test_current_time_freezes_but_content_change_reopens_it(self):
        from final_review import freeze_time_binding
        self.task["review_policy_revision"] = "final-double-review-v1"
        now = datetime.now(timezone.utc)
        self.run["finished_at"] = (now - timedelta(hours=49)).isoformat()
        self.refresh()
        self.assertNotIn("current_status", self.facts())
        self.task["final_review_freeze"] = freeze_time_binding(self.task, self.evidence,
            (now - timedelta(hours=2)).isoformat())
        self.assertIn("current_status", self.facts())
        self.evidence["new_substantive_record"] = True
        self.assertNotIn("current_status", self.facts())

    def test_historical_events_and_applicants_do_not_fill_current_facts(self):
        del self.row["current_status"]
        del self.row["current_owner"]
        self.row.update(applicant="Original applicant", assignees=["Historical name"],
                        legal_events=[{"date": "2001-01-01", "status": "granted"}])
        self.refresh()
        self.assertNotIn("current_status", self.facts())
        self.assertNotIn("rights_holder", self.facts())

    def test_full_claims_accept_but_truncation_and_family_identity_do_not(self):
        self.assertIn("protection_content", self.facts())
        self.row["claims_truncated"] = True
        self.refresh()
        self.assertNotIn("protection_content", self.facts())
        del self.row["claims_truncated"]
        self.row["publication_number"] = "US8888888B2"
        self.row["candidate_id"] = self.candidate["candidate_id"]
        self.refresh()
        self.assertEqual(self.facts(), {})

    def test_nonproduction_or_failed_response_never_counts(self):
        for key, value in (("status", "failed"), ("error_code", "FREE_QUOTA_EXHAUSTED"),
                           ("source_environment", "sandbox")):
            original = deepcopy(self.run)
            self.run[key] = value
            self.refresh()
            self.assertEqual(self.facts(), {})
            self.run.clear(); self.run.update(original)

    def test_blank_api_values_do_not_fill_required_facts(self):
        for value in (" ", [""], {"name": " "}, "unknown"):
            self.row.update(current_owner=value, goods_services=" ", mark_text=" ")
            self.refresh()
            self.assertNotIn("rights_holder", self.facts())
            self.assertNotIn("goods_services", self.facts())
            self.assertNotIn("mark_text", self.facts())
        for value in (" N/A ", {"status": "unknown"}, "unavailable"):
            self.row["current_status"] = value
            self.refresh()
            self.assertNotIn("current_status", self.facts())

    def test_material_requires_exact_identity_and_requested_field(self):
        request = {"source_form": api.FORM, "api_record_identity": self.row["publication_number"],
            "right_type": "patent", "jurisdiction": "US", "evidence_refs": ["E1"], "candidate_id": "C1"}
        request = api.bind_material_candidate(self.task, request, self.candidates)
        self.assertTrue(api.material_fact(self.task, request, {"E1": self.entry}, "status"))
        self.assertFalse(api.material_fact(self.task, request, {"E1": self.entry}, "representative_figures"))
        request["api_record_identity"] = "US0000000B2"
        self.assertFalse(api.material_fact(self.task, request, {"E1": self.entry}, "status"))

    def test_equivalent_provider_field_shapes_do_not_reopen_facts(self):
        other = deepcopy(self.entry)
        run = {**self.run, "run_id": "R2", "provider": "epo_ops"}
        other.update(evidence_id="E2", source_run_id="R2", provider="epo_ops")
        row = other["payload"]["records"][0]
        row.update(current_status={"primary": "ACTIVE"}, current_owner=[" Example  owner "])
        api.annotate_entry(self.task, other, run)
        self.evidence["collections"]["patents"].append(other)
        self.evidence["source_runs"].append(run)
        self.assertTrue({"current_status", "territory", "rights_holder"} <= set(self.facts()))

    def test_partial_views_and_thumbnails_do_not_close_figure_gap(self):
        import base64
        path = self.root / "figure.png"
        path.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jZuoAAAAASUVORK5CYII="))
        self.row["media"] = [{"path": str(path), "sha256": sha256_file(path)}]
        self.refresh()
        self.assertIn("representative_figures", self.facts())
        for gap in ({"images_truncated": True}, {"media_acquisition": {"complete": False}}):
            self.row.update(gap)
            self.refresh()
            self.assertNotIn("representative_figures", self.facts())
            for key in gap:
                self.row.pop(key)
        self.row["media"][0]["is_thumbnail"] = True
        self.refresh()
        self.assertNotIn("representative_figures", self.facts())

    def test_claim_comparison_uses_actual_api_text(self):
        from assessment_v24 import _claim_documents
        docs = _claim_documents(self.evidence, self.plan, self.candidate, {"E1"}, self.task)
        self.assertEqual(docs["E1"]["1"], self.row["claims"][0])

    def test_same_ep_document_static_text_never_supplies_national_status(self):
        self.row.update(publication_number="EP1234567B1", jurisdiction="EP")
        self.entry["jurisdiction"] = self.run["jurisdiction"] = "EP"
        self.candidate.update(publication_number="EP1234567B1", jurisdiction="DE")
        self.refresh()
        facts = self.facts()
        self.assertIn("protection_content", facts)
        self.assertIn("identity", facts)
        self.assertNotIn("current_status", facts)
        self.assertNotIn("territory", facts)
        self.assertNotIn("rights_holder", facts)
        self.candidate["publication_number"] = "DE1234567B1"
        self.assertEqual(self.facts(), {})

    def decision(self):
        self.task["decision_workflow_revision"] = "scenario-triage-v1"
        self.task["serpapi_free_enhancement"] = {"max_queries_per_task": 12}
        return {"candidate_id": "C1", "scenario_id": "product", "scenario_sha256": "f" * 64,
            "jurisdiction": "US", "right_type": "patent", "annotation": {"annotation_id": "D1"}}

    def test_complete_api_record_generates_zero_web_or_duplicate_api_queries(self):
        queries = {}
        self.assertEqual(actions.append(self.task, self.evidence, queries, self.candidate,
            self.decision(), [self.requirement], capabilities={}), [])
        self.assertEqual(queries, {})

    def test_only_missing_claims_requested_and_pending_action_reused(self):
        del self.row["claims"]
        self.refresh()
        queries = {}
        options = {"serpapi_google_patents": {"executable": True}}
        args = (self.task, self.evidence, queries, self.candidate, self.decision(), [self.requirement])
        self.assertEqual(actions.append(*args, capabilities=options), [])
        planned = queries["serpapi_google_patents"][0]
        self.assertEqual(planned["missing_facts"], ["protection_content"])
        actions.append(*args, capabilities=options)
        self.assertEqual(len(queries["serpapi_google_patents"]), 1)
        self.row["claims"] = ["1. A complete claimed hinge."]
        self.refresh()
        self.assertTrue(api.action_facts(self.task, self.evidence, planned))
        self.assertEqual(actions.append(*args, capabilities=options), [])

    def test_bounded_failure_falls_back_only_for_supported_missing_fields(self):
        del self.row["claims"]
        self.refresh()
        req = {**self.requirement, "routes": [{"provider": "uspto_patent_browser", "operation": "candidate_verification"}]}
        queries = {}
        decision = self.decision()
        options = {"serpapi_google_patents": {"executable": True}}
        actions.append(self.task, self.evidence, queries, self.candidate, decision, [req], capabilities=options)
        row = queries["serpapi_google_patents"][0]
        self.evidence["source_runs"].append({"query_id": row["query_id"], "status": "failed", "submission_state": "submitted"})
        actions.append(self.task, self.evidence, queries, self.candidate, decision, [req], capabilities=options)
        fallback = queries["uspto_patent_browser"][0]
        self.assertEqual(fallback["fallback_basis"]["missing_facts"], ["protection_content"])
        self.assertEqual(fallback["fallback_basis"]["attempted_query_ids"], [row["query_id"]])
        self.assertEqual(len(queries["serpapi_google_patents"]), 1)

    def test_unsubmitted_obsolete_scenario_does_not_block_current_followup(self):
        del self.row["claims"]
        self.refresh()
        queries = {}
        options = {"serpapi_google_patents": {"executable": True}}
        decision = self.decision()
        actions.append(self.task, self.evidence, queries, self.candidate, decision, [self.requirement], capabilities=options)
        original = deepcopy(queries["serpapi_google_patents"][0])
        decision = {**decision, "scenario_id": "new-scenario", "scenario_sha256": "e" * 64,
                    "annotation": {"annotation_id": "D2"}}
        actions.append(self.task, self.evidence, queries, self.candidate, decision, [self.requirement], capabilities=options)
        self.assertEqual(queries["serpapi_google_patents"][0], original)
        self.assertEqual(len(queries["serpapi_google_patents"]), 2)
        self.assertEqual(queries["serpapi_google_patents"][1]["scenario_id"], "new-scenario")


if __name__ == "__main__":
    unittest.main()
