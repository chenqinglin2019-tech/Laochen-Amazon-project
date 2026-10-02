"""09B reviewed outcome, weak lead, invalidation and aggregation contracts."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common import atomic_write_json, load_json, now_iso, sha256_file
from stage_risk_stage_b import REVISION, project, record_event, snapshot


class StageRiskStageBTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.task = {"task_id": "T09B", "stage_risk_revision": REVISION,
            "product_change_version": "V1", "target_jurisdictions": ["US", "GB"],
            "assessment_scenarios": [{"scenario_id": "product_entry"}, {"scenario_id": "resale"}],
            "primary_scenario_id": "product_entry",
            "specialty_analysis_events": [{"event_id": "CMP1", "kind": "comparison", "candidate_id": "C1",
                "scenario_id": "product_entry", "jurisdiction": "US", "right_type": "patent"},
                {"event_id": "CMP2", "kind": "comparison", "candidate_id": "C2",
                 "scenario_id": "product_entry", "jurisdiction": "US", "right_type": "patent"}]}
        self.evidence = {"task_id": "T09B", "collections": {"official": [
            {"evidence_id": "EV1", "payload": {"fact": "source one"}},
            {"evidence_id": "EV2", "payload": {"fact": "source two"}}]},
            "source_runs": [], "stage_risk_events": []}
        self.candidates = {"patents": [{"candidate_id": "C1", "right_type": "patent", "jurisdiction": "US"},
                                        {"candidate_id": "C2", "right_type": "patent", "jurisdiction": "US"}]}
        self.save()

    def save(self):
        atomic_write_json(self.path / "task.json", self.task)
        atomic_write_json(self.path / "evidence.json", self.evidence)
        atomic_write_json(self.path / "normalized-candidates.json", self.candidates)

    def scope(self, candidate="C1", country="US", scenario="product_entry"):
        return {"scenario_id": scenario, "jurisdiction": country, "right_type": "patent",
                "product_version": self.task["product_change_version"], "module_id": "utility_patent",
                "candidate_id": candidate}

    def request(self, risk="高", candidate="C1", outcome="CMP1", evidence="EV1", **extra):
        base = {"kind": "review", "actor": "reviewer-one", "reasoning": "read retained facts",
            "scope": self.scope(candidate), "stage_risk": risk, "verification_status": "verified",
            "basis": "verified_comparison", "assessment_date": "2026-09-25",
            "evidence_refs": [evidence, outcome], "outcome_refs": [outcome],
            "supporting_facts": [{"reasoning": "actual product correspondence", "evidence_refs": [evidence]}],
            "counter_facts": [], "comparison": "compared protected points and product facts",
            "adjacent_level_reasoning": "actual conflict supports this level rather than adjacent levels",
            "gaps": [], "weak_leads": [], "confidence": "中",
            "confidence_reasoning": "source readable; limited contrary material",
            "right_applicability_reasoning": "current applicable record in country",
            "counter_evidence_reasoning": "reviewed known counter facts; insufficient to displace",
            "right_state": "active", "right_state_evidence_refs": [evidence]}
        return {**base, **extra}

    def record(self, request):
        self.save()
        event = record_event(self.path, request)
        self.evidence = load_json(self.path / "evidence.json")
        return event

    def supplement(self, **changes):
        path = self.path / "original.txt"
        path.write_text("retained official material", encoding="utf-8")
        item = {"evidence_id": "SUP1", "path": "original.txt", "sha256": sha256_file(path),
                "bytes": path.stat().st_size, "kind": "rights_record", "checked_at": now_iso(),
                "source_url": "https://example.org/official", **changes}
        atomic_write_json(self.path / "supplemental-evidence.json", {"schema": "TEST/1.0", "evidence": [item]})
        return item

    def test_valid_supplement_closes_recursive_dependencies_in_risk_review_and_delivery(self):
        from stage_review_stage_c import _freeze, COVERAGE_SUBJECTS
        from stage_delivery_stage_d import _sanitize_risk
        item = self.supplement()
        self.task["delivery_inspection_revision"] = "delivery-inspection-stage-d-v1"
        self.task["specialty_analysis_events"][0]["evidence_refs"] = ["SUP1"]
        event = self.record(self.request())
        self.assertIn("SUP1", event["ref_fingerprints"])
        scope = {key: self.scope()[key] for key in ("scenario_id", "jurisdiction", "right_type", "product_version")}
        progress = {"plan_version": 1, "by_scope": [{**scope, "completed": 1, "planned": 1}]}
        with patch("stage_review_stage_c.ledger", return_value=progress):
            batch = _freeze(self.task, self.evidence, {"scope": scope, "trigger": "pre_delivery",
                "trigger_reasoning": "freeze checked materials", "item_ids": [event["event_id"]],
                "coverage_notes": [{"subject": subject, "disposition": "reviewed", "reasoning": "checked"}
                                   for subject in sorted(COVERAGE_SUBJECTS)]}, [], task_dir=self.path)
        self.assertEqual(batch["source_facts"]["SUP1"]["row"], item)
        self.assertEqual(batch["missing_source_refs"], [])
        risk = snapshot(self.task, self.evidence, task_dir=self.path)
        self.assertEqual(risk["judgments"][0]["applicability"], "current")
        _, quarantine, _ = _sanitize_risk(self.task, self.evidence, risk, self.path)
        self.assertEqual(quarantine, [])

    def test_supplement_hash_tampering_is_rejected_on_every_projection(self):
        self.supplement()
        self.record(self.request(evidence="SUP1"))
        (self.path / "original.txt").write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "HASH_OR_SIZE_MISMATCH"):
            snapshot(self.task, self.evidence, task_dir=self.path)

    def test_rebound_supplement_changes_suspend_only_judgments_using_the_reference(self):
        item = self.supplement()
        self.record(self.request(evidence="SUP1"))
        self.record(self.request(candidate="C2", outcome="CMP2"))
        item["source_url"] = "https://example.org/different-original"
        atomic_write_json(self.path / "supplemental-evidence.json", {"schema": "TEST/1.0", "evidence": [item]})
        rows = snapshot(self.task, self.evidence, task_dir=self.path)["judgments"]
        self.assertEqual(rows[0]["suspension_reason"], "EVIDENCE_CHANGED_OR_MISSING")
        self.assertEqual(rows[1]["applicability"], "current")

    def test_supplement_conflicting_base_identity_and_outside_paths_are_rejected(self):
        self.supplement(evidence_id="EV1")
        with self.assertRaisesRegex(ValueError, "REFERENCE_COLLISION"):
            self.record(self.request())
        self.supplement(path="../outside.txt")
        with self.assertRaisesRegex(ValueError, "PATH_OUTSIDE_EVIDENCE_ROOT"):
            self.record(self.request())

    def test_supplement_broken_link_is_not_silently_ignored(self):
        path = self.path / "supplemental-evidence.json"
        path.symlink_to(self.path / "missing.json")
        from workflow_v24 import WORKFLOW_CORRECTION_REVISION
        from decision_workflow import REVISION as DECISION_REVISION
        self.task["workflow_correction_revision"] = WORKFLOW_CORRECTION_REVISION
        self.task["decision_workflow_revision"] = DECISION_REVISION
        with self.assertRaises(FileNotFoundError):
            self.record(self.request())

    def test_no_completed_reviewed_outcome_cannot_create_grade(self):
        request = self.request(outcome="EV1", evidence="EV1")
        request["outcome_refs"] = ["EV1"]
        request["evidence_refs"] = ["EV1"]
        with self.assertRaisesRegex(ValueError, "REVIEWED_COMPLETED_OUTCOME"):
            self.record(request)
        self.assertEqual(snapshot(self.task, self.evidence)["overall"]["stage_risk"], None)

    def test_provisional_low_requires_real_zero_review_and_keeps_confidence_empty(self):
        self.evidence["source_runs"].append({"run_id": "RUN0", "scenario_id": "product_entry",
            "jurisdiction": "US", "right_type": "patent", "submission_state": "submitted",
            "status": "no_result", "result_processing": {"returned_count": 0}})
        request = self.request("低", candidate="", outcome="RUN0", evidence="RUN0",
            supporting_facts=[], verification_status="pending", basis="no_specific_lead",
            confidence=None, confidence_reasoning=None,
            gaps=[{"missing_fact": "other necessary searches", "impact": "overall exclusion unresolved",
                   "minimal_action": "review remaining query"}])
        request["evidence_refs"] = ["RUN0"]
        with patch("source_result_processing.progress", return_value={"material_processing_complete": True}):
            self.record(request)
        result = snapshot(self.task, self.evidence)
        self.assertEqual(result["overall"]["stage_risk"], "低")
        self.assertEqual(result["overall"]["display_grade"], "暂定低")
        self.assertEqual(result["overall"]["verification_status"], "pending")
        self.assertIsNone(result["overall"]["confidence"])

    def test_weak_lead_needs_explanation_and_credible_conflict_is_medium(self):
        pending = self.request("低", candidate="C1", outcome="CMP1", evidence="EV1",
            supporting_facts=[], verification_status="pending", basis="weak_leads",
            confidence=None, gaps=[{"missing_fact": "product link", "impact": "conflict unresolved",
                                    "minimal_action": "compare original product"}])
        with self.assertRaisesRegex(ValueError, "WEAK_LEAD"):
            self.record(pending)
        medium = self.request("中", verification_status="pending", basis="credible_conflict",
            confidence=None, gaps=[{"missing_fact": "legal scope", "impact": "final level unresolved",
                                    "minimal_action": "read register"}],
            product_link="same visible mechanism", conflict_point="protected element corresponds")
        self.record(medium)
        self.assertEqual(snapshot(self.task, self.evidence)["overall"]["stage_risk"], "中")

    def test_explained_weak_lead_remains_provisional_low(self):
        pending = self.request("低", supporting_facts=[], verification_status="pending",
            basis="weak_leads", confidence=None,
            gaps=[{"missing_fact": "product connection", "impact": "final verification pending",
                   "minimal_action": "compare original product"}],
            weak_leads=[{"lead": "keyword match only", "why_not_credible_conflict": "product link unproved",
                         "minimal_check": "read original record", "evidence_refs": ["EV1"]}])
        self.record(pending)
        result = snapshot(self.task, self.evidence)
        self.assertEqual(result["overall"]["stage_risk"], "低")
        self.assertEqual(result["judgments"][0]["basis"], "weak_leads")
        self.assertEqual(len(result["judgments"][0]["weak_leads"]), 1)

    def test_failed_run_with_reviewed_material_can_support_partial_judgment(self):
        self.evidence["source_runs"].append({"run_id": "RUN-FAIL", "scenario_id": "product_entry",
            "jurisdiction": "US", "right_type": "patent", "submission_state": "submitted",
            "status": "failed", "result_processing": {"returned_count": 1}})
        request = self.request("低", candidate="", outcome="RUN-FAIL", evidence="EV1",
            supporting_facts=[], verification_status="pending", basis="no_specific_lead",
            confidence=None, gaps=[{"missing_fact": "remaining pages", "impact": "final verification pending",
                                    "minimal_action": "recover only missing page"}])
        request["evidence_refs"] = ["EV1", "RUN-FAIL"]
        with patch("source_result_processing.progress", return_value={"material_processing_complete": True,
                                                                        "returned_count": 1}):
            self.record(request)
        self.assertEqual(snapshot(self.task, self.evidence)["overall"]["stage_risk"], "低")

    def test_high_stays_high_despite_partial_progress_and_low(self):
        high = self.record(self.request())
        low = self.request("低", candidate="C2", outcome="CMP2", evidence="EV2",
            necessary_work_reviewed=True, supporting_facts=[])
        self.record(low)
        plan = {"plan_version": 2, "completed": 20, "planned": 100, "percentage": 20,
                "by_scope": [{"scenario_id": "product_entry", "jurisdiction": "US", "right_type": "patent",
                              "product_version": "V1", "completed": 20, "planned": 100}]}
        result = snapshot(self.task, self.evidence, plan)
        self.assertEqual(result["overall"]["stage_risk"], "高")
        self.assertEqual(result["overall"]["drivers"], [high["event_id"]])
        self.assertEqual(result["review_progress"]["percentage"], 20)

    def test_invalidated_high_pauses_overall_and_preserves_low_partial(self):
        high = self.record(self.request())
        low = self.request("低", candidate="C2", outcome="CMP2", evidence="EV2",
            necessary_work_reviewed=True, supporting_facts=[])
        self.record(low)
        self.task["product_change_history"] = [{"event_id": "CHANGE1"}]
        self.record({"kind": "invalidate", "actor": "reviewer-one", "reasoning": "wrong product version",
            "judgment_id": high["event_id"], "upstream_ref": "CHANGE1",
            "impact": "high conclusion can change", "recovery_action": "targeted comparison review"})
        result = snapshot(self.task, self.evidence)
        self.assertEqual(result["overall"]["applicability"], "pending_recheck")
        self.assertIn("上次等级：高（已暂停适用）", result["overall"]["display_grade"])
        self.assertEqual(result["overall"]["previous_risk"], "高")
        self.assertEqual(result["overall"]["valid_partial_highest"], "低")

    def test_independent_very_high_keeps_overall_when_high_suspends(self):
        high = self.record(self.request())
        very_high = self.request("极高", candidate="C2", outcome="CMP2", evidence="EV2",
            important_exclusions_checked=True)
        self.record(very_high)
        self.task["product_change_history"] = [{"event_id": "CHANGE1"}]
        self.record({"kind": "invalidate", "actor": "reviewer-one", "reasoning": "one comparison invalid",
            "judgment_id": high["event_id"], "upstream_ref": "CHANGE1",
            "impact": "old high may change", "recovery_action": "repeat exact comparison"})
        result = snapshot(self.task, self.evidence)
        self.assertEqual(result["overall"]["stage_risk"], "极高")
        self.assertEqual(result["overall"]["applicability"], "current")
        self.assertEqual(len(result["overall"]["suspended_judgments"]), 1)

    def test_conditional_scenario_stays_out_of_primary(self):
        self.task["specialty_analysis_events"].append({"event_id": "CMP-RES", "kind": "comparison",
            "candidate_id": "C1", "scenario_id": "resale", "jurisdiction": "US", "right_type": "patent"})
        request = self.request("高", outcome="CMP-RES")
        request["scope"]["scenario_id"] = "resale"
        request["evidence_refs"] = ["EV1", "CMP-RES"]
        self.record(request)
        result = snapshot(self.task, self.evidence)
        self.assertIsNone(result["overall"]["stage_risk"])
        self.assertEqual(result["conditional_scenarios"][0]["stage_risk"], "高")

    def test_product_version_change_suspends_prior_judgment(self):
        self.record(self.request())
        self.task["product_change_version"] = "V2"
        result = snapshot(self.task, self.evidence)
        self.assertEqual(result["overall"]["applicability"], "pending_recheck")
        self.assertEqual(result["overall"]["previous_risk"], "高")

    def test_evidence_change_suspends_and_rereview_records_prior(self):
        old = self.record(self.request())
        self.evidence["collections"]["official"][0]["payload"]["fact"] = "corrected source one"
        self.assertEqual(snapshot(self.task, self.evidence)["overall"]["previous_risk"], "高")
        self.record(self.request("中", verification_status="verified", basis="verified_comparison",
            prior_judgment_id=old["event_id"], change_reasoning="corrected product correspondence",
            right_applicability_reasoning=None, counter_evidence_reasoning=None))
        result = snapshot(self.task, self.evidence)
        self.assertEqual(result["overall"]["stage_risk"], "中")
        self.assertEqual(len(result["judgments"]), 1)
        self.assertEqual(len(self.evidence["stage_risk_events"]), 2)

    def test_local_very_low_not_extrapolated_with_open_plan(self):
        request = self.request("极低", basis="decisive_exclusion", scope_complete=True,
            decisive_exclusion_refs=["EV1"])
        self.record(request)
        progress = {"planned": 2, "completed": 1, "by_scope": [{"scenario_id": "product_entry", "right_type": "patent",
            "jurisdiction": "US", "product_version": "V1", "planned": 2, "completed": 1}]}
        result = snapshot(self.task, self.evidence, progress)
        self.assertEqual(result["judgments"][0]["stage_risk"], "极低")
        self.assertEqual(result["overall"]["stage_risk"], "低")
        self.assertEqual(result["by_country"][0]["stage_risk"], "低")

    def test_signal_is_separate_from_current_risk(self):
        self.record({"kind": "signal_review", "actor": "reviewer-one", "reasoning": "read original event",
            "scope": {"scenario_id": "product_entry", "jurisdiction": "US", "product_version": "V1"},
            "signal_type": "enforcement", "evidence_refs": ["EV1"],
            "event_layer": "party_claim",
            "product_link": "possibly related product", "source_status": "party allegation",
            "event_time": "2026-09-20", "signal_reasoning": "not a final decision",
            "review_condition": "new official proceeding"})
        result = snapshot(self.task, self.evidence)
        self.assertEqual(len(result["signals"]), 1)
        self.assertIsNone(result["overall"]["stage_risk"])

    def test_old_task_unchanged_and_unreviewed_scope_has_no_grade(self):
        old = dict(self.task)
        del old["stage_risk_revision"]
        view = {"entries": []}
        self.assertIs(project(old, view, self.evidence), view)
        view["review_progress"] = {"by_scope_module": [{"scenario_id": "product_entry",
            "jurisdiction": "US", "right_type": "patent", "product_version": "V1",
            "module_id": "utility_patent"}]}
        result = project(self.task, view, self.evidence)
        self.assertIsNone(result["stage_risk"]["scopes_without_any_judgment"][0]["stage_risk"])


if __name__ == "__main__":
    unittest.main()
