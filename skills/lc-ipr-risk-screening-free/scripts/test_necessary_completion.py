"""Offline completion gates; synthetic obligations do not assert live recall."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import assessment_estimate as assessment
from common import atomic_write_json, load_json, sha256_json
import necessary_completion as completion
from test_assessment_workflow_correction import corrected_fixture
from test_assessment_estimate_scenarios import refresh


class NecessaryCompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ipr-necessary-completion-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.env = patch.dict("os.environ", {"LC_IPR_OFFLINE_TESTS": "1"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.values = corrected_fixture(self.path)
        self.task, self.evidence, self.candidates, self.plan, self.ledger, self.first, self.second = self.values
        self.task["completion_policy_revision"] = completion.REVISION
        from workflow_v24 import product_identity_digest
        self.task["product"]["analysis"]["identity_sha256"] = product_identity_digest(self.task["product"], task=self.task)
        brand = self.task["assessment_scenarios"][1]
        for review in (self.first, self.second):
            review["assessments"].append({**deepcopy(review["assessments"][0]),
                "scenario_id": brand["scenario_id"], "scenario_sha256": brand["scenario_sha256"]})
        refresh(self.values)

    def scopes(self, complete=True):
        return [{"scenario_id": s["scenario_id"], "scenario_sha256": s["scenario_sha256"],
            "jurisdiction": "US", "right_type": "trademark_word", "status": "满足已定义要求",
            "retrieval_status": "complete" if complete else "incomplete", "triage_status": "complete",
            "verification_status": "complete", "queries": [], "obligations": [], "queues": {},
            "gaps": [] if complete else ["SOURCE_UNAVAILABLE"]} for s in self.task["assessment_scenarios"]]

    def calculate(self, complete=True):
        with patch("assessment_estimate.coverage_by_scope", return_value=self.scopes(complete)), \
                patch("workflow_v24.scenario_execution_gaps", return_value=[]):
            return assessment.compute_assessment(*self.values)

    def save(self):
        for name, value in zip(("task.json", "evidence.json", "normalized-candidates.json", "search-plan.json",
                "materiality-annotations.json", "first-review.json", "second-review.json"), self.values):
            atomic_write_json(self.path / name, value)

    def blocked_view(self, state="awaiting_access", reason="OPTIONAL_CREDENTIALS_MISSING"):
        return {"revision": "workflow-correction-v1", "status": "incomplete", "entries": [
            {"work_id": "WORK-" + scope["scenario_id"], "scenario_id": scope["scenario_id"], "jurisdiction": "US",
             "right_type": "trademark_word", "provider": "uspto_tsdr", "kind": "source_lookup", "state": state,
             "reason": reason} for scope in self.scopes()], "counts": {}, "unresolved_scopes": self.scopes(False)}

    def proof(self, result, view, **kwargs):
        with patch("workflow_v24.derive_work_view", return_value=view):
            return completion.publication_context(*self.values[:5], result,
                task_dir=self.path, evidence_root=self.path, **kwargs)

    def test_marker_changes_digest_and_invalid_revision_is_rejected(self):
        strict = assessment.review_digest(*[self.evidence, self.candidates, self.ledger, self.plan, self.task])
        old = deepcopy(self.task)
        old.pop("completion_policy_revision")
        self.assertNotEqual(strict, assessment.review_digest(self.evidence, self.candidates, self.ledger, self.plan, old))
        old["completion_policy_revision"] = "unrecognized"
        with self.assertRaisesRegex(ValueError, "COMPLETION_POLICY_INVALID"):
            completion.enabled(old)

    def test_empty_dual_review_cannot_publish_final_or_stage_and_writes_nothing(self):
        self.first["assessments"] = []
        self.second["assessments"] = []
        self.save()
        from publish_report import publish
        for mode in ("final", "stage"):
            with self.subTest(mode=mode), patch("assessment_estimate.coverage_by_scope", return_value=self.scopes(False)), \
                    patch("workflow_v24.scenario_execution_gaps", return_value=[]), \
                    self.assertRaisesRegex(ValueError, "PUBLICATION_SCOPE_REVIEW_REQUIRED"):
                publish(self.path, self.path / "first-review.json", self.path / "second-review.json",
                    output_dir=self.path / mode, mode=mode, stop_reason="Sources unavailable" if mode == "stage" else None)
            self.assertFalse((self.path / mode).exists())

    def test_review_projection_matches_shared_scope_gaps_and_requires_independence(self):
        self.second["assessments"].pop()
        work = completion.review_work(*self.values[:5], self.scopes(), self.first, self.second, evidence_root=self.path)
        self.assertEqual(len(work["entries"]), 1)
        self.assertEqual(work["entries"][0]["action_id"], "review:second")
        self.assertEqual(work["entries"][0]["scenario_id"], "brand_reuse")
        self.second["review_context"]["session_id"] = self.first["review_context"]["session_id"]
        with self.assertRaisesRegex(ValueError, "SECOND_REVIEW_NOT_INDEPENDENT"):
            completion.review_work(*self.values[:5], self.scopes(), self.first, self.second, evidence_root=self.path)
        self.second["review_context"]["session_id"] = "second-independent"
        self.second["review_context"]["evidence_digest"] = "stale"
        with self.assertRaisesRegex(ValueError, "REVIEW_CONTEXT_INVALID"):
            completion.review_work(*self.values[:5], self.scopes(), self.first, self.second, evidence_root=self.path)

    def test_stage_cannot_hide_agent_work_or_arbitrary_blocker(self):
        result = self.calculate(False)
        for state in ("ready", "awaiting_review", "submission_unknown"):
            with self.subTest(state=state), self.assertRaisesRegex(ValueError, "STAGE_AGENT_WORK_REMAINS"):
                self.proof(result, self.blocked_view(state), mode="stage", stop_reason="Stop now")
        with self.assertRaisesRegex(ValueError, "STAGE_EXTERNAL_BLOCKER_NOT_ESTABLISHED"):
            self.proof(result, self.blocked_view("blocked", "unknown"), mode="stage", stop_reason="Unavailable")

    def test_stage_with_real_external_state_keeps_known_high_risk(self):
        result = self.calculate(False)
        before = deepcopy(result["overall"])
        proof = self.proof(result, self.blocked_view(), mode="stage", stop_reason="Account access unavailable")
        self.assertEqual(proof["mode"], "stage")
        self.assertEqual(result["overall"], before)
        self.assertEqual(result["overall"]["risk"], "高")
        self.assertEqual(result["status"], "incomplete")
        with self.assertRaisesRegex(ValueError, "PUBLICATION_NECESSARY_WORK_INCOMPLETE"):
            self.proof(result, self.blocked_view())

    def test_rate_cooldown_and_recovery_exhaustion_are_external_blockers(self):
        for code in ("BROWSER_RATE_LIMITED", "BROWSER_RATE_LIMIT_COOLDOWN", "BROWSER_RATE_LIMIT_RECOVERY_EXHAUSTED", "BROWSER_RATE_LIMIT_RECOVERY_UNVERIFIED"):
            proof = self.proof(self.calculate(False), self.blocked_view(reason=code), mode="stage", stop_reason="Source rate limited")
            self.assertEqual(proof["remaining_work"][0]["reason"], code)

    def test_pending_scope_is_reviewed_but_requires_a_matching_external_blocker(self):
        for review in (self.first, self.second):
            row = review["assessments"][0]
            row.update(risk=None, assessment_status="pending", pending_reasoning="Source access unavailable")
        result = self.calculate(False)
        self.assertEqual(result["scenario_summaries"][0]["completion"]["queues"]["scope_unassessed"], [])
        self.proof(result, self.blocked_view(), mode="stage", stop_reason="Account access unavailable")
        view = self.blocked_view()
        view["entries"].pop(0)
        with self.assertRaisesRegex(ValueError, "WITHOUT_BLOCKER"):
            self.proof(result, view, mode="stage", stop_reason="Account access unavailable")

    def test_unknown_capability_remains_agent_work_and_classification_has_a_route(self):
        requirement = {"requirement_id": "R", "jurisdiction": "US", "right_type": "patent",
            "routes": [{"provider": "uspto_patent_browser", "operation": "patent_recall"}]}
        self.task["coverage_requirements"] = [requirement]
        view = self.blocked_view()
        view["entries"] = [{"work_id": "W", "state": "ready", "kind": "plan_repair",
            "reason": "R:AXIS_MISSING:classification"}]
        for caps in ({}, {"uspto_patent_browser": {"executable": False, "reason": "unknown"}}):
            refined = completion.refine_work_view(self.task, view, self.plan, caps)
            self.assertEqual(refined["entries"][0]["state"], "ready")
            self.assertEqual(refined["entries"][0]["route_options"][0]["provider"], "uspto_patent_browser")
        caps = {"uspto_patent_browser": {"executable": False, "reason": "optional_credentials_missing"}}
        self.assertEqual(completion.refine_work_view(self.task, view, self.plan, caps)["entries"][0]["state"], "awaiting_access")

    def test_unsupported_image_axis_is_a_gap_not_a_fake_completed_query(self):
        self.task["coverage_requirements"] = [{"requirement_id": "R", "jurisdiction": "US", "right_type": "design",
            "routes": [{"provider": "uspto_patent_browser", "operation": "design_recall"}]}]
        view = self.blocked_view()
        view["entries"] = [{"work_id": "W", "state": "ready", "kind": "plan_repair", "reason": "R:AXIS_MISSING:image"}]
        result = completion.refine_work_view(self.task, view, self.plan, {})
        self.assertEqual(result["entries"][0]["reason"], "NO_SUPPORTED_ROUTE")
        self.assertEqual(result["status"], "incomplete")

    def test_phonetic_and_asset_description_are_not_fake_routes(self):
        tm = {"jurisdiction": "US", "right_type": "trademark_word",
            "routes": [{"provider": "uspto_tmsearch_browser", "operation": "word_recall"}]}
        self.assertEqual(completion._route_options(self.task, tm, "phonetic"), [])
        self.assertTrue(completion._route_options(self.task, tm, "text"))
        tm.update(right_type="trademark_figurative", routes=[{"provider": "asset_provenance", "operation": "provenance_review"}])
        self.assertEqual(completion._route_options(self.task, tm, "description"), [])
        self.assertTrue(completion._route_options(self.task, tm, "classification"))

    def test_existing_rate_limited_alternative_does_not_create_infinite_replanning(self):
        primary = self.task["assessment_scenarios"][0]
        self.task["coverage_requirements"] = [{"requirement_id": "R", "jurisdiction": "US", "right_type": "patent",
            "routes": [{"provider": "epo_ops", "operation": "search"}, {"provider": "uspto_patent_browser", "operation": "patent_recall"}]}]
        base = {"scenario_id": primary["scenario_id"], "scenario_sha256": primary["scenario_sha256"],
            "jurisdiction": "US", "right_type": "patent", "requirement_ids": ["R"], "search_dimension": "text"}
        plan = {"queries": {"epo_ops": [{**base, "query_id": "E"}], "uspto_patent_browser": [{**base, "query_id": "P"}]}}
        view = {"status": "incomplete", "entries": [
            {**base, "work_id": "WE", "query_id": "E", "provider": "epo_ops", "state": "awaiting_access", "kind": "source_lookup", "reason": "OPTIONAL_CREDENTIALS_MISSING"},
            {**base, "work_id": "WP", "query_id": "P", "provider": "uspto_patent_browser", "state": "awaiting_access", "kind": "source_lookup", "reason": "BROWSER_RATE_LIMIT_RECOVERY_EXHAUSTED"}],
            "unresolved_scopes": [{**base, "gaps": ["RETRIEVAL_TRUNCATED"]}]}
        caps = {"epo_ops": {"executable": False, "reason": "optional_credentials_missing"}, "uspto_patent_browser": {"executable": True}}
        result = completion.refine_work_view(self.task, view, plan, caps)
        self.assertEqual(result["counts"]["ready"], 0)
        self.assertEqual([e["reason"] for e in result["entries"]], ["OPTIONAL_CREDENTIALS_MISSING", "BROWSER_RATE_LIMIT_RECOVERY_EXHAUSTED"])
        plan["queries"]["uspto_patent_browser"] = []
        view["entries"].pop()
        self.assertEqual(completion.refine_work_view(self.task, view, plan, caps)["entries"][0]["reason"], "AUTHORIZED_ALTERNATIVE_REQUIRES_PLANNING")

    def test_query_rejection_becomes_scoped_repair_and_stale_product_stays_actionable(self):
        view = self.blocked_view("blocked", "USPTO_QUERY_REJECTED")
        self.assertTrue(all(e["kind"] == "plan_repair" and e["state"] == "ready"
            for e in completion.refine_work_view(self.task, view, self.plan, {})["entries"]))
        self.task["product"]["analysis"]["identity_sha256"] = "stale"
        view = completion.refine_work_view(self.task, self.blocked_view(), self.plan, {})
        self.assertTrue(any(e["reason"] == "PRODUCT_ANALYSIS_STALE" and e["state"] == "ready" for e in view["entries"]))

    def test_snapshots_drop_opaque_fields_and_bind_original_bytes(self):
        snapshots = {"source-capabilities.json": {"task_id": self.task["task_id"], "arbitrary": "not-retained",
            "sources": [{"provider": "uspto_tsdr", "executable": False, "reason": "optional_credentials_missing",
                         "credentials": {"opaque": "not-retained"}, "token": "not-retained"}]},
            "browser-execution-status.json": {"task_id": self.task["task_id"], "queries": [], "cookies": "not-retained"}}
        proof = self.proof(self.calculate(False), self.blocked_view(), mode="stage", stop_reason="Account missing", snapshots=snapshots)
        self.assertNotIn("not-retained", str(proof))
        self.assertEqual(proof["snapshot_source_digests"]["source-capabilities.json"], sha256_json(snapshots["source-capabilities.json"]))

    def test_final_publish_and_independent_rebuild_use_same_frozen_inputs(self):
        from publish_report import publish
        import report_estimate as report
        self.save()
        original_task = (self.path / "task.json").read_bytes()
        for name in ("source-capabilities.json", "browser-execution-status.json"):
            value = {"task_id": self.task["task_id"], "sources": []} if name.startswith("source") else {"task_id": self.task["task_id"], "queries": []}
            atomic_write_json(self.path / name, value)
        with patch("assessment_estimate.coverage_by_scope", return_value=self.scopes()), \
                patch("workflow_v24.scenario_execution_gaps", return_value=[]), \
                patch("runtime_v24.capabilities", side_effect=AssertionError("No live capability check")), \
                patch("assessment_estimate.compute_assessment", wraps=assessment.compute_assessment) as calculate:
            outcome = publish(self.path, self.path / "first-review.json", self.path / "second-review.json", output_dir=self.path / "out")
            self.assertEqual(calculate.call_count, 2)
            self.assertEqual(outcome["file_integrity"], "valid")
            task = load_json(self.path / "out/task.json")
            self.assertEqual(report.validate_run(self.path, task, output_dir=self.path / "out"), [])
            data = load_json(self.path / "out/report-data.json")
            self.assertEqual(data["publication"]["mode"], "final")
            result = load_json(self.path / "out/assessment.json")
            report.build_bundle(self.path, task, self.evidence, result, self.candidates,
                {"schema_version": "1.0", "task_id": task["task_id"], "entries": []}, self.plan, output_dir=self.path / "standalone")
            result["publication"]["stop_reason"] = "tampered"
            self.assertTrue(assessment.validate_assessment(self.path, task, result))
            atomic_write_json(self.path / "source-capabilities.json", {"task_id": task["task_id"], "sources": [], "changed": True})
            self.assertTrue(report.validate_run(self.path, task, output_dir=self.path / "out"))
        self.assertEqual((self.path / "task.json").read_bytes(), original_task)

    def test_stage_publish_is_recomputed_and_stop_proof_cannot_be_removed(self):
        from publish_report import publish
        import report_estimate as report
        self.save()
        with patch("assessment_estimate.coverage_by_scope", return_value=self.scopes(False)), \
                patch("workflow_v24.scenario_execution_gaps", return_value=[]), \
                patch("workflow_v24.derive_work_view", return_value=self.blocked_view()), \
                patch("runtime_v24.capabilities", side_effect=AssertionError("No live capability check")):
            publish(self.path, self.path / "first-review.json", self.path / "second-review.json",
                output_dir=self.path / "stage", mode="stage", stop_reason="Official account access remains unavailable")
            task = load_json(self.path / "stage/task.json")
            self.assertEqual(report.validate_run(self.path, task, output_dir=self.path / "stage"), [])
            data = load_json(self.path / "stage/report-data.json")
            self.assertEqual(data["overall"]["risk"], "高")
            self.assertEqual(data["overall"]["business_completion"], "incomplete")
            self.assertIn("阶段报告停止原因", (self.path / "stage/report.md").read_text())
            result = load_json(self.path / "stage/assessment.json")
            result.pop("publication")
            self.assertTrue(assessment.validate_assessment(self.path, task, result))

    def test_next_work_does_not_load_current_credentials_or_change_investigation_status(self):
        from workflow_v24 import work_view_from_dir
        self.save()
        with patch("assessment_v24.scenario_coverage_by_scope", return_value=self.scopes()), \
                patch("workflow_v24.load_skill_config", side_effect=AssertionError("No current credentials")):
            view = work_view_from_dir(self.path)
        self.assertEqual(view["status"], "complete")
        self.assertEqual(view["review_work"]["status"], "incomplete")
        self.assertEqual(len(view["review_work"]["entries"]), 4)

    def test_actual_seven_asset_investigations_cannot_be_skipped_by_stage_publication(self):
        from test_scenario_planning import ScenarioPlanningTests
        from workflow_v24 import work_view_from_dir, product_identity_digest, generate_plan
        from report_estimate import RIGHT_MODULES
        from publish_report import publish
        f = ScenarioPlanningTests()
        f.setUp()
        self.addCleanup(f.tearDown)
        f.task["completion_policy_revision"] = completion.REVISION
        f.task["product"].pop("own_brand", None)
        f.task["product"]["mark_inventory"] = [{"mark_id": "M", "scenario_ids": ["brand_reuse"],
            "form": "figurative", "graphic_description": "A simple circle logo", "evidence_refs": ["E1"]}]
        f.task["product"]["analysis"]["identity_sha256"] = product_identity_digest(f.task["product"], task=f.task)
        f.save()
        f.plan = generate_plan(f.path, expand=True)
        work = work_view_from_dir(f.path)
        asset_work = [r for r in work["entries"] if r.get("provider") == "asset_provenance" and r["state"] == "ready"]
        self.assertEqual(len(asset_work), 7)
        reviews = []
        for role in ("first", "second"):
            review = {"reviewer": role, "review_context": {"session_id": "actual-projection-" + role,
                "evidence_digest": work["review_work"]["evidence_digest"], "first_review_visible": False},
                "coverage_confidence_cap": "低", "coverage_confidence_reasoning": "Necessary investigations remain unexecuted.",
                "assessments": []}
            reviews.append(review)
            atomic_write_json(f.path / (role + "-review.json"), review)
        for mode in ("final", "stage"):
            with self.assertRaisesRegex(ValueError, "PUBLICATION_SCOPE_REVIEW_REQUIRED"):
                publish(f.path, f.path / "first-review.json", f.path / "second-review.json",
                    output_dir=f.path / ("empty-" + mode), mode=mode,
                    stop_reason="Missing optional accounts" if mode == "stage" else None)
        for role, review in zip(("first", "second"), reviews):
            for entry in work["review_work"]["entries"]:
                if entry["action_id"] != "review:" + role:
                    continue
                scenario = next(s for s in f.task["assessment_scenarios"] if s["scenario_id"] == entry["scenario_id"])
                review["assessments"].append({"scenario_id": scenario["scenario_id"], "scenario_sha256": scenario["scenario_sha256"],
                    "jurisdiction": entry["jurisdiction"], "right_type": entry["right_type"], "candidate_id": "",
                    "module_id": RIGHT_MODULES[entry["right_type"]], "risk": None, "assessment_status": "pending",
                    "pending_reasoning": "Necessary public investigation remains unexecuted.", "title": "Scope pending",
                    "scope": "US scope", "reasoning": "Investigation pending", "confidence_reasoning": "Insufficient evidence",
                    "evidence_confidence": "低", "evidence_refs": [], "supporting_evidence": [], "counter_evidence": [],
                    "no_supporting_evidence_reasoning": "Not investigated", "no_counter_evidence_reasoning": "Not investigated",
                    "assumptions": [], "raise_if": [], "lower_if": [], "human_checks": []})
            atomic_write_json(f.path / (role + "-review.json"), review)
        with self.assertRaisesRegex(ValueError, "STAGE_AGENT_WORK_REMAINS") as caught:
            publish(f.path, f.path / "first-review.json", f.path / "second-review.json",
                output_dir=f.path / "stage", mode="stage", stop_reason="Missing optional accounts")
        for entry in asset_work:
            self.assertIn(entry["work_id"], str(caught.exception))
        self.assertFalse((f.path / "stage").exists())


if __name__ == "__main__":
    unittest.main()
