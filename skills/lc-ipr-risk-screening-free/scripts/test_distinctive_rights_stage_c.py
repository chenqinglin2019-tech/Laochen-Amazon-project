"""07C trade-dress boundaries and public-enforcement event contracts."""
import unittest

import test_distinctive_rights_review as prior


def review(outcome="unknown"):
    return prior.judgment(outcome)


class StageCTests(unittest.TestCase):
    def setUp(self):
        self.previous = prior.ReviewTests()
        self.previous.setUp()
        self.fx = self.previous.fx
        self.addCleanup(self.fx.tmp.cleanup)

    def trade_dress(self):
        material, fact = self.previous.copyright(right_type="trade_dress")
        return material, fact

    def claim(self, **changes):
        intake = next(row for row in reversed(self.fx.task["distinctive_rights_events"])
                      if row["kind"] == "intake")
        values = dict(appearance_version="art-v1",
            product_version_sha256=intake["product_version_sha256"],
            use_context="printed on strap", claimed_object_id="art",
            boundary_status="defined", boundary_reasoning="Read the actual included product appearance",
            features=[{"feature_id": "F-shape", "kind": "shape", "appearance_version": "art-v1",
                       "description": "Observed curved edge", "evidence_refs": ["E1"]}],
            combination_relation="One curved feature in the actual appearance",
            evidence_refs=["E1"])
        values.update(changes)
        return self.fx.add("trade_dress_claim", **values)

    def regime(self, claim, material, fact, **changes):
        values = dict(claim_event_id=claim["event_id"], regime="us_trade_dress",
            basis_status="reviewed", legal_basis_or_gap="Read target-region rule",
            conditions=[{"condition_id": "source_identity", "question": "Is source identity shown?",
                         "review": review("unknown")}],
            material_event_ids=[material["event_id"]], fact_event_ids=[fact["event_id"]],
            evidence_refs=["E1"])
        values.update(changes)
        return self.fx.add("trade_dress_regime", **values)

    def use(self, claim, regime, material, fact, **changes):
        values = dict(claim_event_id=claim["event_id"], regime_event_id=regime["event_id"],
            public_use=review("unknown"), source_identification=review("unknown"),
            material_event_ids=[material["event_id"]], fact_event_ids=[fact["event_id"]],
            evidence_refs=["E1"])
        values.update(changes)
        return self.fx.add("trade_dress_use", **values)

    def function(self, claim, regime, material, fact, **changes):
        values = dict(claim_event_id=claim["event_id"], regime_event_id=regime["event_id"],
            feature_reviews=[{"feature_id": "F-shape", "source_nature": "technical_claim",
                              "review": review("claimed_functional")}],
            combination_review=review("unknown"),
            material_event_ids=[material["event_id"]], fact_event_ids=[fact["event_id"]],
            evidence_refs=["E1"])
        values.update(changes)
        return self.fx.add("trade_dress_functionality", **values)

    def compare(self, claim, regime, material, fact, **changes):
        values = dict(claim_event_id=claim["event_id"], regime_event_id=regime["event_id"],
            use_context="printed on strap", visual=review("unknown"),
            source_confusion=review("unknown"),
            material_event_ids=[material["event_id"]], fact_event_ids=[fact["event_id"]],
            evidence_refs=["E1"])
        values.update(changes)
        return self.fx.add("trade_dress_comparison", **values)

    def signal(self, material, **changes):
        layers = {key: review("unknown") for key in
                  ("claim", "platform_action", "procedure", "formal_decision")}
        values = dict(event_key="CASE-1", event_identity_basis="Same concrete case number",
            source_kind="repost", source_document_id="NEWS-1",
            party_identity="Same-name entity", right_or_claim="Trade dress allegation",
            affected_product="Unknown product", event_jurisdiction="US",
            association="unknown", association_reasoning="Identity and product remain unlocated",
            layers=layers, time_points=[], current_status="unknown",
            original_source_gap_or_ref="Original case file not yet read",
            material_event_ids=[material["event_id"]], evidence_refs=["E1"])
        values.update(changes)
        return self.fx.add("enforcement_signal", **values)

    def observation(self, **changes):
        if not hasattr(self, "enforcement_scope_id"):
            self.enforcement_scope(needed=True,
                planned_query_ids=["Q-CASE", "Q-OTHER", "Q-PENDING"])
        values = dict(query_id="Q-CASE", query_scope="US public case search for this object",
            outcome="not_queried", reasoning="This necessary source has not run",
            enforcement_scope_event_id=self.enforcement_scope_id)
        values.update(changes)
        return self.fx.add("enforcement_observation", **values)

    def enforcement_scope(self, **changes):
        values = dict(needed=False, reasoning="This selected object has no current enforcement search need",
                      planned_query_ids=[], evidence_refs=["E1"])
        values.update(changes)
        row = self.fx.add("enforcement_scope", **values)
        self.enforcement_scope_id = row["event_id"]
        return row

    def test_claim_cannot_mix_versions_or_unincluded_packaging(self):
        self.trade_dress()
        with self.assertRaisesRegex(ValueError, "CLAIM_SCOPE_INVALID"):
            self.claim(claimed_object_id="unselected-packaging")
        features = [{"feature_id": "F-shape", "kind": "shape",
                     "appearance_version": "other-packaging-v2",
                     "description": "Different version", "evidence_refs": ["E1"]}]
        with self.assertRaisesRegex(ValueError, "FEATURE_INVALID"):
            self.claim(features=features)
        row = self.claim()
        self.assertEqual(row["claimed_object_id"], "art")

    def test_unknown_claim_boundary_keeps_specific_gap(self):
        self.trade_dress()
        with self.assertRaisesRegex(ValueError, "BOUNDARY_GAP_REQUIRED"):
            self.claim(boundary_status="unknown")
        self.claim(boundary_status="unknown", boundary_gap="Layout boundary unclear")
        self.assertIn("M07_TRADE_DRESS_BOUNDARY_OPEN", self.fx.blockers())

    def test_rule_is_local_and_conditions_not_inherited(self):
        material, fact = self.trade_dress()
        claim = self.claim()
        with self.assertRaisesRegex(ValueError, "CURRENT_SELECTED_REQUIRED"):
            self.regime(claim, material, fact, jurisdiction="GB")
        row = self.regime(claim, material, fact)
        self.assertEqual(row["jurisdiction"], "US")
        self.assertIn("M07_TRADE_DRESS_USE_PENDING", self.fx.blockers())

    def test_public_sales_do_not_prove_source_identification(self):
        material, fact = self.trade_dress()
        claim = self.claim()
        regime = self.regime(claim, material, fact)
        public = {**review("supported"), "actor": "Seller", "use_date": "2020-01-01",
                  "appearance_version": "art-v1", "jurisdiction": "US"}
        self.use(claim, regime, material, fact, public_use=public)
        self.assertIn("M07_TRADE_DRESS_USE_AXIS_OPEN", self.fx.blockers())
        with self.assertRaisesRegex(ValueError, "SOURCE_IDENTIFICATION_REQUIRED"):
            self.use(claim, regime, material, fact, public_use=public,
                     source_identification=review("supported"))

    def test_technical_claim_is_not_whole_combination_functionality(self):
        material, fact = self.trade_dress()
        claim = self.claim()
        regime = self.regime(claim, material, fact)
        with self.assertRaisesRegex(ValueError, "FUNCTIONALITY_OVERCLAIM"):
            self.function(claim, regime, material, fact, feature_reviews=[{
                "feature_id": "F-shape", "source_nature": "technical_claim",
                "review": review("verified_functional")}])
        self.function(claim, regime, material, fact)
        self.assertIn("M07_TRADE_DRESS_FUNCTIONALITY_OPEN", self.fx.blockers())

    def test_visual_similarity_does_not_complete_confusion_question(self):
        material, fact = self.trade_dress()
        claim = self.claim()
        regime = self.regime(claim, material, fact)
        visual = {**review("corresponds"), "similarities": "Same silhouette",
                  "differences": "Different colors", "whole_relationship": "Only silhouette overlaps"}
        row = self.compare(claim, regime, material, fact, visual=visual)
        self.assertEqual(row["source_confusion"]["outcome"], "unknown")
        self.assertIn("M07_TRADE_DRESS_COMPARISON_AXIS_OPEN", self.fx.blockers())

    def test_changed_fact_pauses_only_dependent_trade_dress_reviews(self):
        material, fact = self.trade_dress()
        claim = self.claim()
        regime = self.regime(claim, material, fact)
        self.use(claim, regime, material, fact)
        self.fx.add("impact", impact_reasoning="New archived view changes use date",
                    affected_fact_event_ids=[fact["event_id"]], evidence_refs=["E1"])
        view = self.fx.view()["scopes"][0]["substantive_reviews"]
        self.assertTrue(view["trade_dress_claim_currently_usable"])
        self.assertFalse(view["trade_dress_use_currently_usable"])
        self.assertIn("M07_TRADE_DRESS_RECHECK_PENDING", self.fx.blockers())

    def test_same_name_news_cannot_become_verified_association(self):
        material, _ = self.trade_dress()
        with self.assertRaisesRegex(ValueError, "ASSOCIATION_UNPROVEN"):
            self.signal(material, association="verified")
        row = self.signal(material)
        self.assertEqual(row["association"], "unknown")
        self.assertIn("M07_ENFORCEMENT_SIGNAL_OPEN", self.fx.blockers())

    def test_complaint_and_settlement_do_not_become_formal_decision(self):
        material, _ = self.trade_dress()
        layers = {key: review("unknown") for key in
                  ("claim", "platform_action", "procedure", "formal_decision")}
        layers["claim"] = {**review("documented"), "statement": "Complaint filed"}
        layers["procedure"] = {**review("documented"), "statement": "Settlement reported"}
        row = self.signal(material, layers=layers)
        self.assertEqual(row["layers"]["formal_decision"]["outcome"], "unknown")
        layers["formal_decision"] = {**review("documented"), "statement": "Infringement found",
                                     "decision_level": "final judgment"}
        with self.assertRaisesRegex(ValueError, "FORMAL_DECISION_SOURCE_REQUIRED"):
            self.signal(material, layers=layers, prior_signal_event_id=row["event_id"],
                        update_reasoning="News reposted alleged decision")

    def test_reposts_share_one_event_identity_and_do_not_replace_original(self):
        material, _ = self.trade_dress()
        first = self.signal(material)
        with self.assertRaisesRegex(ValueError, "UPDATE_LINK_REQUIRED"):
            self.signal(material)
        self.signal(material, prior_signal_event_id=first["event_id"],
                    update_reasoning="Another site reposted the same case",
                    source_document_id="NEWS-2")
        events = self.fx.view()["scopes"][0]["substantive_reviews"]["enforcement_signals"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_count"], 1)
        self.assertEqual(len(events[0]["source_event_ids"]), 2)

    def test_repost_does_not_downgrade_original_and_change_reopens_relation(self):
        material, fact = self.trade_dress()
        original = self.signal(material, source_kind="original", association="verified",
            association_evidence_refs=["E1"], fact_event_ids=[fact["event_id"]],
            party_match_basis="Read original party identifier",
            product_match_basis="Read original product identity",
            right_match_basis="Read actual asserted right",
            current_status="supported", source_checked_at="2026-09-25T01:00:00Z",
            current_status_statement="Original source shows current proceeding")
        self.signal(material, prior_signal_event_id=original["event_id"],
            update_reasoning="Same case reposted", source_document_id="NEWS-2")
        row = self.fx.view()["scopes"][0]["substantive_reviews"]["enforcement_signals"][0]
        self.assertEqual(row["association"], "verified")
        self.assertEqual(row["reviewed_event_id"], original["event_id"])
        self.fx.add("impact", impact_reasoning="Original party identity corrected",
                    affected_fact_event_ids=[fact["event_id"]], evidence_refs=["E1"])
        row = self.fx.view()["scopes"][0]["substantive_reviews"]["enforcement_signals"][0]
        self.assertFalse(row["currently_usable"])
        self.assertEqual(row["association"], "unknown")

    def test_formal_decision_requires_actual_official_material(self):
        self.trade_dress()
        official = self.fx.material(track="public_facts", source_form="official_decision",
                                    document_id="CASE-DECISION")
        layers = {key: review("unknown") for key in
                  ("claim", "platform_action", "procedure", "formal_decision")}
        layers["formal_decision"] = {**review("documented"),
            "statement": "Decision addresses this identified product only",
            "decision_level": "final judgment"}
        row = self.signal(official, source_kind="original", source_document_id="CASE-DECISION",
                          layers=layers)
        self.assertEqual(row["layers"]["formal_decision"]["outcome"], "documented")

    def test_old_repost_cannot_claim_current_status(self):
        material, _ = self.trade_dress()
        with self.assertRaisesRegex(ValueError, "CURRENT_SOURCE_REQUIRED"):
            self.signal(material, current_status="supported", source_checked_at="2026-09-25T01:00:00Z",
                        current_status_statement="Still active")

    def test_zero_failure_and_unqueried_sources_stay_distinct(self):
        self.trade_dress()
        self.fx.evidence["source_runs"] = [
            {"run_id": "R-ZERO", "query_id": "Q-CASE", "jurisdiction": "US",
             "right_type": "enforcement", "status": "no_result"},
            {"run_id": "R-FAIL", "query_id": "Q-OTHER", "jurisdiction": "US",
             "right_type": "enforcement", "status": "failed"}]
        self.fx.save()
        self.observation(outcome="no_result", source_run_id="R-ZERO")
        with self.assertRaisesRegex(ValueError, "RECEIPT_REQUIRED"):
            self.observation(outcome="no_result", source_run_id="R-FAIL")
        self.observation(query_id="Q-OTHER", outcome="failed", source_run_id="R-FAIL")
        self.observation(query_id="Q-PENDING", outcome="not_queried")
        rows = self.fx.view()["scopes"][0]["substantive_reviews"]["enforcement_observations"]
        self.assertEqual([row["outcome"] for row in rows], ["no_result", "failed", "not_queried"])
        self.assertIn("M07_ENFORCEMENT_SOURCE_OPEN", self.fx.blockers())

    def test_enforcement_necessity_precedes_search(self):
        self.trade_dress()
        self.assertIn("M07_ENFORCEMENT_SCOPE_PENDING", self.fx.blockers())
        self.enforcement_scope()
        self.assertNotIn("M07_ENFORCEMENT_SEARCH_PENDING", self.fx.blockers())
        with self.assertRaisesRegex(ValueError, "CURRENT_SCOPE_REQUIRED"):
            self.fx.add("enforcement_observation", query_id="Q-CASE",
                        query_scope="US case search", outcome="not_queried",
                        reasoning="Not yet run", enforcement_scope_event_id=self.enforcement_scope_id)


if __name__ == "__main__":
    unittest.main()
