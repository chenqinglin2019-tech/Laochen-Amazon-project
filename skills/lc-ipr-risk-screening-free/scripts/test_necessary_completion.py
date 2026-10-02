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

    def test_publication_collector_returns_all_independent_failures_without_mutation(self):
        result = self.calculate(False)
        view = self.blocked_view('ready', 'UNPROVED_REASON')
        before = deepcopy((self.values, result, view))
        with patch('workflow_v24.derive_work_view', return_value=view):
            collected = completion.collect_publication_issues(*self.values[:5], result,
                task_dir=self.path, evidence_root=self.path, mode='stage')
        self.assertFalse(collected['ready'])
        self.assertIsNone(collected['context'])
        codes = {row['code'] for row in collected['issues']}
        self.assertTrue({'STAGE_STOP_REASON_REQUIRED', 'STAGE_AGENT_WORK_REMAINS',
            'STAGE_EXTERNAL_BLOCKER_NOT_ESTABLISHED', 'STAGE_UNRESOLVED_SCOPE_WITHOUT_BLOCKER'} <= codes)
        self.assertEqual((self.values, result, view), before)
        # Legacy entry keeps its first failure and original exception contract.
        with self.assertRaisesRegex(ValueError, 'STAGE_STOP_REASON_REQUIRED'):
            self.proof(result, view, mode='stage')

    def test_preparation_collects_each_unproved_limit_without_reviewing_or_authorizing(self):
        task = {'schema_version': '2.4-free', 'task_id': 'OFFLINE-COLLECT',
            'assessment_policy': 'evidence-estimate-v1', 'workflow_correction_revision': 'workflow-correction-v1',
            'completion_policy_revision': 'necessary-work-v3'}
        evidence = {'source_runs': []}
        plan = {'queries': {}}
        result = {'status': 'incomplete', 'coverage': {'scopes': []},
            'review': {'input_reviews': {'first': None, 'second': None}}, 'scenario_summaries': []}
        view = {'entries': [{'work_id': 'W-1', 'state': 'blocked', 'reason': 'UNKNOWN_REASON'},
                            {'work_id': 'W-2', 'state': 'blocked', 'reason': 'OTHER_UNKNOWN'}],
            'status': 'incomplete', 'unresolved_scopes': []}
        with patch.object(completion, 'review_work') as review, \
                patch.object(completion, '_delivery_limit_valid', return_value=False):
            collected = completion.collect_publication_issues(task, evidence, {}, plan, {}, result,
                mode='evidence', preparation=True, prepared_view=view)
        review.assert_not_called()
        self.assertEqual(collected['errors'], ['EVIDENCE_LIMITATION_NOT_ESTABLISHED: W-1',
            'EVIDENCE_LIMITATION_NOT_ESTABLISHED: W-2'])
        self.assertIsNone(collected['context'])
        self.assertTrue(collected['preparation_only'])
        view['entries'] = []
        with patch.object(completion, 'review_work') as review:
            valid = completion.collect_publication_issues(task, evidence, {}, plan, {}, result,
                mode='evidence', preparation=True, prepared_view=view)
        self.assertTrue(valid['ready'])
        self.assertIsNone(valid['context'])
        review.assert_not_called()

    def test_partial_report_discloses_reviewed_scope_unknown_without_rights_proof(self):
        task = {"assessment_revision": "partial-evidence-v2"}
        evidence = {"collections": {"product": [{"evidence_id": "CONTEXT", "provider": "amazon_browser"}]},
                    "source_runs": []}
        row = {"scenario_id": "product_entry", "jurisdiction": "US", "right_type": "enforcement",
            "candidate_id": None, "assessment_status": "pending", "risk": None, "right_state": "unknown",
            "pending_reasoning": "No specific event or sufficient investigation evidence retained",
            "evidence_refs": ["CONTEXT"], "review_resolution": {"method": "independent_agreement"}}
        def limits(value=row, current_task=task):
            return completion._reviewed_fact_limitations({"assessments": [value]}, evidence, task=current_task)
        before = deepcopy(row)
        result = limits()
        self.assertEqual(result[0]["kind"], "reviewed_scope_gap")
        self.assertEqual(result[0]["coverage_status"], "unknown")
        self.assertEqual(result[0]["context_evidence_sha256"]["CONTEXT"], sha256_json(evidence["collections"]["product"][0]))
        self.assertEqual(row, before)
        for changes in ({"risk": "低"}, {"candidate_id": "C1"}, {"right_state": "active"},
                        {"review_resolution": {}}, {"evidence_refs": ["MISSING"]}, {"evidence_refs": []}):
            with self.subTest(changes=changes):
                self.assertEqual(limits({**row, **changes}), [])
        self.assertEqual(limits(current_task={}), [])

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

    def test_hash_bound_provider_fault_wait_can_be_published_without_claiming_zero(self):
        result = self.calculate(False)
        view = self.blocked_view(reason="SOURCE_FAULT_UNVERIFIED")
        proof = self.proof(result, view, mode="stage", stop_reason="Exact provider fault receipt retained")
        self.assertEqual(proof["mode"], "stage")
        self.assertTrue(all(item["reason"] == "SOURCE_FAULT_UNVERIFIED" for item in proof["remaining_work"]))

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

    def test_empty_brand_mark_planning_gaps_reuse_existing_user_wait(self):
        scope = {"scenario_id": "product_entry", "jurisdiction": "US", "right_type": "trademark_word"}
        waiting = {"work_id": "WAIT-BRAND", **scope, "clue_id": "object:own-brand",
            "kind": "user_information", "state": "awaiting_user", "reason": "DISCOVERY_CLUE_AWAITING_INFORMATION"}
        gaps = [{"work_id": "GAP-TEXT", **scope, "kind": "plan_repair", "state": "ready",
                    "reason": "browser_adapter_requires_real_route_acceptance",
                    "planning_gap": "COV-US-TRADEMARK_WORD-RECALL:AXIS_MISSING:text"},
                 {"work_id": "GAP-PHONETIC", **scope, "kind": "plan_repair", "state": "blocked",
                    "reason": "NO_SUPPORTED_ROUTE",
                    "planning_gap": "COV-US-TRADEMARK_WORD-RECALL:AXIS_MISSING:phonetic"},
                 {"work_id": "GAP-LANGUAGE", **scope, "kind": "plan_repair", "state": "ready",
                    "reason": "LANGUAGE_TERM_REPAIR_REQUIRED",
                    "planning_gap": "COV-US-TRADEMARK_WORD-RECALL:LOCAL_LANGUAGE_MISSING"},
                 {"work_id": "GAP-TERMS", **scope, "kind": "plan_repair", "state": "ready",
                    "code": "API_DISCOVERY_TERMS_MISSING", "reason": "API_DISCOVERY_TERMS_MISSING"}]
        view = {"status": "incomplete", "entries": [*gaps, waiting], "unresolved_scopes": [scope]}
        with patch.object(completion, "_empty_word_mark_wait_clues", return_value={"object:own-brand"}):
            result = completion.refine_work_view(self.task, view, self.plan, {})
        self.assertEqual([entry["work_id"] for entry in result["entries"]], ["WAIT-BRAND"])
        self.assertEqual(result["entries"][0]["state"], "awaiting_user")
        self.assertEqual(result["status"], "incomplete")
        # Without the matching current user dependency, the route gap remains actionable.
        view["entries"] = deepcopy(gaps)
        with patch.object(completion, "_empty_word_mark_wait_clues", return_value={"object:own-brand"}):
            result = completion.refine_work_view(self.task, view, self.plan, {})
        self.assertEqual({entry["work_id"] for entry in result["entries"]},
            {"GAP-TEXT", "GAP-PHONETIC", "GAP-LANGUAGE", "GAP-TERMS"})

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

    def test_validated_bounded_semantic_wait_is_not_rewritten_as_alternative_plan_work(self):
        primary = self.task["assessment_scenarios"][0]
        self.task["coverage_requirements"] = [{"requirement_id": "R", "jurisdiction": "US", "right_type": "patent",
            "routes": [{"provider": "epo_ops", "operation": "search"}, {"provider": "uspto_patent_browser", "operation": "patent_recall"}]}]
        row = {"scenario_id": primary["scenario_id"], "query_id": "Q", "jurisdiction": "US", "right_type": "patent",
            "requirement_ids": ["R"], "search_dimension": "text", "discovery_scope": {"mode": "bounded"}}
        plan = {"queries": {"epo_ops": [row], "uspto_patent_browser": []}}
        entry = {"work_id": "W", "scenario_id": primary["scenario_id"], "jurisdiction": "US", "right_type": "patent",
            "query_id": "Q", "provider": "epo_ops", "plan_entry_sha256": sha256_json(row), "direction_id": "D",
            "source_run_id": "R1", "state": "awaiting_access", "kind": "plan_repair",
            "reason": "BOUNDED_DISCOVERY_OFFICIAL_COVERAGE_UNVERIFIED"}
        view = {"status": "incomplete", "entries": [entry], "unresolved_scopes": []}
        with patch("necessary_completion._current_semantic_wait", return_value=True):
            result = completion.refine_work_view(self.task, view, plan, {"uspto_patent_browser": {"executable": True}},
                evidence=self.evidence, candidates=self.candidates, ledger=self.ledger, task_dir=self.path)
        self.assertEqual(result["entries"][0]["reason"], "BOUNDED_DISCOVERY_OFFICIAL_COVERAGE_UNVERIFIED")
        with patch("necessary_completion._current_semantic_wait", return_value=False):
            result = completion.refine_work_view(self.task, view, plan, {"uspto_patent_browser": {"executable": True}},
                evidence=self.evidence, candidates=self.candidates, ledger=self.ledger, task_dir=self.path)
        self.assertEqual(result["entries"][0]["reason"], "AUTHORIZED_ALTERNATIVE_REQUIRES_PLANNING")

    def test_classification_bounded_stop_is_axis_limited_and_uses_dependency_direction(self):
        scenario = self.task["assessment_scenarios"][0]
        row = {"query_id": "Q-CLASS", "action_purpose": "discovery", "search_dimension": "classification",
            "operation": "design_recall",
            "jurisdiction": "US", "right_type": "design", "requirement_ids": ["R"],
            "product_dependencies": [{"scenario_id": scenario["scenario_id"], "right_type": "design",
                "direction_id": "design-overall"}]}
        run = {"run_id": "RUN-CLASS", "provider": "uspto_patent_browser", "query_id": "Q-CLASS",
            "plan_entry_sha256": sha256_json(row), "status": "success"}
        task = deepcopy(self.task)
        evidence = {"source_runs": [run]}
        entry = {"scenario_id": scenario["scenario_id"], "jurisdiction": "US", "right_type": "design"}
        requirement = {"requirement_id": "R", "routes": [
            {"provider": "uspto_patent_browser", "operation": "design_recall"}]}
        seen = []
        def exact_wait(*args, **kwargs):
            seen.append(args[7].get("direction_id"))
            return args[7].get("direction_id") == "design-overall"
        with patch("necessary_completion._current_semantic_wait", side_effect=exact_wait), \
                patch("workflow_v24.necessary_scenario_row_bindings", return_value=[{"scenario_id": scenario["scenario_id"]}]):
            proof = completion._current_axis_bounded_stop(task, entry, requirement, "classification",
                {"queries": {"uspto_patent_browser": [row]}}, evidence, self.candidates, self.ledger,
                task_dir=self.path)
        self.assertEqual(seen, ["design-overall"])
        self.assertEqual(proof[0]["coverage_status"], "unknown")
        self.assertFalse(completion._current_axis_bounded_stop(task, entry, requirement, "text",
            {"queries": {"uspto_patent_browser": [row]}}, evidence, self.candidates, self.ledger,
            task_dir=self.path))
        text_row = {**row, "query_id": "Q-TEXT", "operation": "design_recall", "search_dimension": "text"}
        text_run = {**run, "run_id": "RUN-TEXT", "query_id": "Q-TEXT",
            "plan_entry_sha256": sha256_json(text_row)}
        with patch("necessary_completion._current_semantic_wait", side_effect=exact_wait), \
                patch("workflow_v24.necessary_scenario_row_bindings", return_value=[{"scenario_id": scenario["scenario_id"]}]):
            self.assertTrue(completion._current_axis_bounded_stop(task, entry, requirement, "text",
                {"queries": {"uspto_patent_browser": [text_row]}}, {"source_runs": [text_run]},
                self.candidates, self.ledger, task_dir=self.path))
            self.assertFalse(completion._current_axis_bounded_stop(task, entry,
                {**requirement, "routes": [{"provider": "serper_web", "operation": "search"}]}, "text",
                {"queries": {"serper_web": [{**text_row, "operation": "search"}]}},
                {"source_runs": [{**text_run, "provider": "serper_web"}]}, self.candidates,
                self.ledger, task_dir=self.path))

    def test_axis_limitation_coexists_with_other_actionable_scope_work(self):
        scope = {"scenario_id": "product_entry", "jurisdiction": "US", "right_type": "design"}
        axis = {**scope, "work_id": "AXIS", "state": "ready", "kind": "plan_repair",
            "planning_gap": "R:AXIS_MISSING:classification", "reason": "browser_adapter_requires_real_route_acceptance"}
        sibling = {**scope, "work_id": "SIBLING", "state": "ready", "kind": "agent_investigation",
            "reason": "OTHER_PURPOSE_REVIEW_REQUIRED"}
        view = {"status": "incomplete", "entries": [axis, sibling], "unresolved_scopes": [scope]}
        with patch("necessary_completion._bounded_discovery_proofs", return_value={tuple(scope.values()): [
                    {"run_id": "RUN", "evidence_refs": ["EV"], "query_id": "Q",
                     "source_run_refs": [{"run_id": "RUN", "sha256": "HASH"}]}]}), \
                patch("necessary_completion._figurative_na_proofs", return_value={}), \
                patch("necessary_completion._axis_route_limits", return_value=(True, [{"provider": "official",
                    "direction_id": "design-overall", "coverage_status": "unknown",
                    "reason": "BOUNDED_DISCOVERY_OFFICIAL_COVERAGE_UNVERIFIED"}])):
            result = completion._resolve_evidence_limits(self.task, view, self.plan, {}, self.evidence,
                self.candidates, self.ledger, task_dir=self.path)
        projected = next(row for row in result["entries"] if row["work_id"] == "AXIS")
        self.assertEqual(projected["reason"], "BOUNDED_DISCOVERY_OFFICIAL_COVERAGE_UNVERIFIED")
        self.assertEqual(projected["official_verification"], "not_verified")
        self.assertEqual(next(row for row in result["entries"] if row["work_id"] == "SIBLING")["state"], "ready")

    def test_professional_design_wait_requires_exact_recomputed_packet(self):
        scope = {"candidate_id": "CAND-D", "scenario_id": "product_entry", "jurisdiction": "US", "right_type": "design"}
        delivery = {"kind": "professional_wait", "gap_event_id": "GAP", "official_verification": "not_verified"}
        entry = {**scope, "kind": "professional_review", "state": "awaiting_access",
            "reason": "SPECIALTY_PROFESSIONAL_SCOPE_WAIT", "unit_id": "UNIT-D", "delivery_limit": delivery}
        expected = {**entry, "delivery_limit": deepcopy(delivery)}
        with patch("specialty_analysis.professional_wait_entry", return_value=expected) as helper:
            self.assertTrue(completion._delivery_limit_valid(entry, self.task, self.evidence,
                self.plan, {}, candidates=self.candidates, ledger=self.ledger))
            helper.assert_called_once()
        entry["reason"] = "arbitrary stop prose"
        with patch("specialty_analysis.professional_wait_entry", return_value=expected):
            self.assertFalse(completion._delivery_limit_valid(entry, self.task, self.evidence,
                self.plan, {}, candidates=self.candidates, ledger=self.ledger))

    def test_stage_accepts_only_current_professional_wait_as_external_blocker(self):
        result = self.calculate(False)
        wait = {"work_id": "WAIT-PRO", "scenario_id": "product_entry", "jurisdiction": "US",
            "right_type": "design", "candidate_id": "CAND-D", "unit_id": "UNIT-D",
            "kind": "professional_review", "state": "awaiting_access",
            "reason": "SPECIALTY_PROFESSIONAL_SCOPE_WAIT", "delivery_limit": {"kind": "professional_wait"}}
        view = self.blocked_view()
        view["entries"].append(wait)
        with patch("necessary_completion._professional_wait_valid", return_value=True):
            proof = self.proof(result, view, mode="stage", stop_reason="Awaiting external design line interpretation")
        self.assertIn(wait, proof["remaining_work"])
        with patch("necessary_completion._professional_wait_valid", return_value=False), \
                self.assertRaisesRegex(ValueError, "STAGE_EXTERNAL_BLOCKER_NOT_ESTABLISHED"):
            self.proof(result, view, mode="stage", stop_reason="Awaiting external design line interpretation")

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
            self.assertEqual(calculate.call_count, 1)
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

    def test_actual_asset_investigations_cannot_be_skipped_by_stage_publication(self):
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
        # The fixture contains reference-only product images.  Those do not
        # create a licence obligation, leaving the seven applicable public
        # investigations below.  Keep this exact count so a planner change
        # cannot silently make stage publication easier.
        self.assertEqual(len(asset_work), 7)
        reviews = []
        for role in ("first", "second"):
            review = {"reviewer": role, "review_context": {"session_id": "actual-projection-" + role,
                "evidence_digest": work["review_work"]["evidence_digest"], "first_review_visible": False,
                "execution": {"agent_id": "fixture-" + role, "run_id": "empty-fixture-run-" + role,
                              "input_digest": work["review_work"]["evidence_digest"], "assessment_digest": sha256_json([])}},
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
            # New tasks require a real execution attestation for each review.
            # This synthetic fixture supplies distinct, deterministic sessions
            # while still leaving the asset investigations outstanding.
            review["review_context"]["execution"] = {"agent_id": "fixture-" + role,
                "run_id": "fixture-run-" + role, "input_digest": work["review_work"]["evidence_digest"],
                "assessment_digest": sha256_json(review["assessments"])}
            atomic_write_json(f.path / (role + "-review.json"), review)
        with self.assertRaisesRegex(ValueError, "STAGE_AGENT_WORK_REMAINS") as caught:
            publish(f.path, f.path / "first-review.json", f.path / "second-review.json",
                output_dir=f.path / "stage", mode="stage", stop_reason="Missing optional accounts")
        for entry in asset_work:
            self.assertIn(entry["work_id"], str(caught.exception))
        self.assertFalse((f.path / "stage").exists())


class SelectedPresenceProjectionTests(unittest.TestCase):
    def _inputs(self, right_type):
        candidate_id = "CAND-test-" + right_type
        selected = {"candidate_id": candidate_id, "scenario_id": "s1", "jurisdiction": "US",
            "right_type": right_type, "current": True, "decision": "selected",
            "annotation": {"candidate_id": candidate_id, "annotation_id": "ANN-1"}}
        task = {"specialty_analysis_revision": "specialty-analysis-v1"}
        view = {"entries": [{"scenario_id": "s1", "jurisdiction": "US", "right_type": right_type,
            "kind": "plan_repair", "state": "ready", "reason": "SELECTED_EXPANSION_UNPLANNED:" + candidate_id}]}
        return candidate_id, selected, task, view

    def test_patent_expansion_is_limited_only_by_recomputed_current_delegation(self):
        cid, selected, task, view = self._inputs("patent")
        delegated = {"candidate_id": cid, "scenario_id": "s1", "jurisdiction": "US", "right_type": "patent",
            "state": "blocked", "reason": "SPECIALTY_DISCOVERY_SCOPE_DELEGATED",
            "delivery_limit": {"kind": "specialty_discovery_delegation", "review_event_id": "EV-1"}}
        with patch("decision_workflow.triage_summary", return_value={"records": [selected]}), \
             patch("specialty_analysis.project", return_value={"scopes": []}), \
             patch("specialty_analysis.work_entries", return_value=[delegated]), \
             patch.object(completion, "_delivery_limit_valid", return_value=True):
            completion._project_selected_expansion_limits(task, view, [], {}, {}, {}, {}, {}, task_dir=Path("."))
        item = view["entries"][0]
        self.assertEqual(item["reason"], "SELECTED_EXPANSION_WITH_CURRENT_DELEGATION")
        self.assertEqual(item["state"], "blocked")
        self.assertEqual(item["official_verification"], "not_verified")
        self.assertEqual(item["delivery_limit"]["kind"], "selected_expansion_delegated")

        _, _, task, view = self._inputs("patent")
        with patch("decision_workflow.triage_summary", return_value={"records": [selected]}), \
             patch("specialty_analysis.project", return_value={"scopes": []}), \
             patch("specialty_analysis.work_entries", return_value=[delegated]), \
             patch.object(completion, "_delivery_limit_valid", return_value=False):
            completion._project_selected_expansion_limits(task, view, [], {}, {}, {}, {}, {}, task_dir=Path("."))
        self.assertEqual(view["entries"][0]["state"], "ready")
        self.assertTrue(view["entries"][0]["reason"].startswith("SELECTED_EXPANSION_UNPLANNED:"))

    def test_design_expansion_requires_exact_bounded_candidate_proof(self):
        cid, selected, task, view = self._inputs("design")
        module_row = {"candidate_id": cid, "scenario_id": "s1", "jurisdiction": "US", "right_type": "design",
            "state": "awaiting_access", "reason": "SPECIALTY_PROFESSIONAL_SCOPE_WAIT"}
        proof = {"kind": "selected_expansion_bounded", "candidate_id": cid,
            "source_run_id": "RUN-1", "coverage_status": "unknown", "official_verification": "not_verified"}
        with patch("decision_workflow.triage_summary", return_value={"records": [selected]}), \
             patch("specialty_analysis.project", return_value={"scopes": []}), \
             patch("specialty_analysis.work_entries", return_value=[module_row]), \
             patch.object(completion, "_selected_design_expansion_proof", return_value=proof):
            completion._project_selected_expansion_limits(task, view, [], {}, {}, {}, {}, {}, task_dir=Path("."))
        item = view["entries"][0]
        self.assertEqual(item["reason"], "BOUNDED_SELECTED_DESIGN_EXPANSION_UNVERIFIED")
        self.assertEqual(item["coverage_status"], "unknown")
        self.assertEqual(item["delivery_limit"], proof)

        _, _, task, view = self._inputs("design")
        with patch("decision_workflow.triage_summary", return_value={"records": [selected]}), \
             patch("specialty_analysis.project", return_value={"scopes": []}), \
             patch("specialty_analysis.work_entries", return_value=[module_row]), \
             patch.object(completion, "_selected_design_expansion_proof", return_value=None):
            completion._project_selected_expansion_limits(task, view, [], {}, {}, {}, {}, {}, task_dir=Path("."))
        self.assertEqual(view["entries"][0]["state"], "ready")
        self.assertTrue(view["entries"][0]["reason"].startswith("SELECTED_EXPANSION_UNPLANNED:"))

    def test_selected_verification_proof_keeps_unknowns_and_rejects_incomplete_m06(self):
        cid = "CAND-test-verification"
        selected = {"candidate_id": cid, "scenario_id": "s1", "jurisdiction": "US",
            "right_type": "design", "current": True, "decision": "selected",
            "annotation": {"candidate_id": cid, "annotation_id": "ANN-1"}}
        entry = {"candidate_id": cid, "scenario_id": "s1", "jurisdiction": "US", "right_type": "design"}
        scope = {**{key: entry[key] for key in ("candidate_id", "scenario_id", "jurisdiction", "right_type")},
            "intake_event_id": "INTAKE-1", "results": [
                {"kind": "fact", "fact_kind": "identity", "outcome": "supported", "currently_usable": True},
                {"kind": "fact", "fact_kind": "protection", "outcome": "supported", "currently_usable": True},
                {"kind": "comparison", "outcome": "unknown", "currently_usable": True}]}
        module_row = {**{key: entry[key] for key in ("candidate_id", "scenario_id", "jurisdiction", "right_type")},
            "state": "blocked", "reason": "CURRENT_STATUS_ROUTE_UNAVAILABLE"}
        proof = completion._selected_verification_disposition(entry, selected, {"scopes": [scope]}, [module_row])
        self.assertEqual(proof["kind"], "selected_verification_disposition")
        self.assertEqual(proof["coverage_status"], "unknown")
        self.assertEqual(proof["official_verification"], "not_verified")
        self.assertIsNone(completion._selected_verification_disposition(entry, selected,
            {"scopes": [{**scope, "results": scope["results"][:2]}]}, [module_row]))
        self.assertIsNone(completion._selected_verification_disposition(entry, selected,
            {"scopes": [scope]}, [{**module_row, "state": "awaiting_review"}]))

        projected_entry = {**entry, "state": "blocked", "reason": "SELECTED_VERIFICATION_CURRENT_DISPOSITION_UNVERIFIED",
            "limitation_kind": "candidate_verification_pending", "official_verification": "not_verified",
            "coverage_status": "unknown", "delivery_limit": proof}
        with tempfile.TemporaryDirectory() as tmp, \
             patch("decision_workflow.triage_summary", return_value={"records": [selected]}), \
             patch("workflow_v24.resolved_work_view", return_value={"specialty_analysis": {"scopes": [scope]}}), \
             patch("specialty_analysis.work_entries", return_value=[module_row]):
            self.assertTrue(completion._delivery_limit_valid(projected_entry, {}, {}, {}, {}, candidates={},
                ledger={}, task_dir=Path(tmp)))
        changed = {**scope, "results": scope["results"][:2]}
        with tempfile.TemporaryDirectory() as tmp, \
             patch("decision_workflow.triage_summary", return_value={"records": [selected]}), \
             patch("workflow_v24.resolved_work_view", return_value={"specialty_analysis": {"scopes": [changed]}}), \
             patch("specialty_analysis.work_entries", return_value=[module_row]):
            self.assertFalse(completion._delivery_limit_valid(projected_entry, {}, {}, {}, {}, candidates={},
                ledger={}, task_dir=Path(tmp)))


if __name__ == "__main__":
    unittest.main()
