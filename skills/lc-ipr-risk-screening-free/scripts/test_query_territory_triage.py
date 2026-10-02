"""Public search territory is not a demonstrated rights jurisdiction."""
from copy import deepcopy
import unittest

import decision_workflow as workflow
import test_triage_scope as base


class PublicQueryTerritoryTests(unittest.TestCase):
    def setUp(self):
        self.f = base.TriageScopeTests()
        self.f.setUp()
        self.task = self.f.task
        self.task["retrieval_workflow_revision"] = "api-first-v3"
        self.candidate = self.f.candidate
        self.candidate.pop("publication_number")
        self.candidate.update(right_type="unknown", retrieval_workflow_revision="api-first-v3",
                              source="serpapi_google_lens", source_index="google_lens",
                              candidate_nature="visual_match", sources=[{
                                  "provider": "serpapi_google_lens", "jurisdiction": "US", "query_id": "Q-US"}])
        self.candidates = {"copyright_assets": [self.candidate]}

    def annotation(self, **changes):
        decision = {"annotation_id": "DRAFT-1", "scenario_id": "product_entry", "decision": "selected",
            "reviewer": "offline-agent", "annotated_at": "2026-09-29T00:00:00Z",
            "reason": "Retained card shows the scoped product", "reading_level": "result_record",
            "basis_summary": "Public result only; no rights territory established", "evidence_refs": ["E1"],
            "reopen_conditions": ["New identity evidence"],
            "candidate_relation": self.f.basis(gaps=["right_type", "target_jurisdiction"]),
            "comparison": self.f.comparison()}
        decision.update(changes)
        return workflow.make_annotation(self.task, "copyright_assets", self.candidate, decision,
                                        evidence=self.f.evidence)

    def summary(self):
        return workflow.triage_summary(self.task, self.candidates, self.f.ledger, evidence=self.f.evidence)

    def test_lens_uses_one_unlocated_scope_without_mutating_retained_candidate(self):
        before = deepcopy(self.candidate)
        self.assertEqual([r["jurisdiction"] for r in self.summary()["records"]], ["UNLOCATED"])
        annotation = self.annotation()
        self.assertEqual(annotation["jurisdiction"], "UNLOCATED")
        self.f.ledger["annotations"].append(annotation)
        summary = self.summary()
        self.assertEqual(summary["counts"]["selected"], 1)
        self.assertEqual(summary["counts"]["unreviewed"], 0)
        self.assertEqual(len(summary["records"]), 1)
        self.assertEqual(workflow.effective_decision(self.task, self.f.ledger, "copyright_assets", self.candidate,
            "product_entry", evidence=self.f.evidence)["decision"], "selected")
        self.assertEqual(workflow.effective_selected_candidates(self.task, self.candidates, self.f.ledger,
            evidence=self.f.evidence), [])
        self.assertEqual(self.candidate, before)

    def test_serper_web_and_image_cards_do_not_inherit_search_market(self):
        for provider, index, nature in (("serper_web", "google_search", "web_result"),
                                       ("serper_images", "google_images", "visual_match")):
            with self.subTest(provider=provider):
                self.candidate.update(source=provider, source_index=index, candidate_nature=nature)
                self.assertEqual(workflow.candidate_triage_origin(self.task, self.candidate), "UNLOCATED")
                self.assertEqual(self.annotation()["jurisdiction"], "UNLOCATED")
                self.assertEqual([r["jurisdiction"] for r in self.summary()["records"]], ["UNLOCATED"])

    def test_legacy_task_and_legacy_candidate_behavior_is_preserved(self):
        for task_revision, candidate_revision in ((None, "api-first-v3"), ("api-first-v2", "api-first-v3"),
                                                   ("api-first-v3", "api-first-v2")):
            with self.subTest(task=task_revision, candidate=candidate_revision):
                self.task["retrieval_workflow_revision"] = task_revision
                self.candidate["retrieval_workflow_revision"] = candidate_revision
                self.assertEqual(self.annotation()["jurisdiction"], "US")
                self.assertEqual([r["jurisdiction"] for r in self.summary()["records"]], ["US"])

    def test_intrinsic_patent_or_other_unknown_record_keeps_country(self):
        for updates in ({"right_type": "patent"}, {"candidate_nature": "registered_record"},
                        {"source": "epo_ops", "source_index": "epo_ops"},
                        {"source": "serper_patents", "source_index": "google_patents"}):
            with self.subTest(updates=updates):
                candidate = {**self.candidate, **updates}
                self.assertEqual(workflow.candidate_triage_origin(self.task, candidate), "US")

    def test_explicit_country_decision_remains_visible(self):
        annotation = self.annotation(jurisdiction="US")
        self.f.ledger["annotations"].append(annotation)
        self.assertEqual(next(row for row in self.summary()["records"]
                              if row["jurisdiction"] == "US")["decision"], "selected")
        self.assertEqual(annotation["jurisdiction"], "US")

    def test_reviewed_country_identity_takes_precedence_over_query_parameter(self):
        self.candidate["field_resolutions"] = {"jurisdiction": {"event_id": "IDCOR-1",
            "evidence_refs": ["E1"], "selected_value": "US"}}
        self.assertEqual(self.annotation()["jurisdiction"], "US")
        self.assertEqual([r["jurisdiction"] for r in self.summary()["records"]], ["US"])
        self.candidate["field_resolutions"]["jurisdiction"]["selected_value"] = "GB"
        self.assertEqual(workflow.candidate_triage_origin(self.task, self.candidate), "UNLOCATED")

    def test_country_gap_remains_required_for_query_only_territory(self):
        with self.assertRaisesRegex(ValueError, "TRIAGE_IDENTITY_GAPS_REQUIRED"):
            self.annotation(candidate_relation=self.f.basis(gaps=["right_type"]))


if __name__ == "__main__":
    unittest.main()
