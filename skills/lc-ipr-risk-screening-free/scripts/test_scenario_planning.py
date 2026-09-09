"""Offline scenario planning/dispatch/coverage contracts; no live IP evidence."""
import copy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common import atomic_write_json, load_json, sha256_json
from decision_workflow import make_annotation, effective_decision
from annotate_materiality import empty_materiality_ledger
from generate_search_plan import entry
from workflow_v24 import (append_candidate_actions, bind_scenario_action, generate_plan, product_identity_digest,
                          reconcile_scenario_actions, scenario_dispatch_block, scenario_dispatch_block_from_dir,
                          validated_query_cancellation, validated_query_substitution)
from assessment_v24 import coverage_by_scope, _scenario_action_complete
from provider_utils import PLAN_META_KEYS, query_identity
from workflow_v24 import SCENARIO_META_KEYS


class ScenarioPlanningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        subprocess.run([sys.executable, str(Path(__file__).with_name("create_task.py")), "--url", "https://www.amazon.com/dp/B012345678",
                        "--jurisdictions", "US", "--output-dir", str(self.path)], capture_output=True, check=True)
        self.task = load_json(self.path / "task.json")
        self.task.pop("retrieval_workflow_revision", None)
        self.task.pop("retrieval_policy", None)
        from common import serper_free_enhancement, serpapi_free_enhancement
        self.task["serper_free_enhancement"] = serper_free_enhancement(False)
        self.task["serpapi_free_enhancement"] = serpapi_free_enhancement(False)
        self.task.pop("completion_policy_revision", None)  # Frozen scenario routing/consumer compatibility fixture.
        self.task.pop("recall_planning_revision", None)  # This fixture isolates scenario routing from clue handoff.
        self.task["state"] = "collecting"
        self.task["product"].update(actual_asin="B012345678", variant={"confirmed": True, "value": "fixture"},
                                    brand="TEST", own_brand="TEST", title="Synthetic strap", language="en", structure=["strap with holes"], specifications={})
        self.task["query_terms"] = [{"kind": "structural_feature", "value": "strap holes", "language": "en", "derived_from": "product.structure[0]"},
                                    {"kind": "design", "value": "lid strap", "language": "en", "derived_from": "product.structure[0]"}]
        self.task["product"]["analysis"] = {"status": "confirmed", "identity_sha256": product_identity_digest(self.task["product"], task=self.task)}
        atomic_write_json(self.path / "task.json", self.task)
        self.evidence = load_json(self.path / "evidence.json")
        self.candidate = {"candidate_id": "SYNTHETIC-C1", "normalization_key": "US:trademark_word:88418732", "jurisdiction": "US",
                          "right_type": "trademark_word", "serial_number": "88418732", "mark_text": "TEST", "goods_services": ["Straps"],
                          "material": True, "material_reason": "exact_product_brand_match", "owner": "Test Owner", "evidence_refs": ["E1"]}
        self.candidates = {"schema_version": "2.4-free", "task_id": self.task["task_id"], "patents": [],
                           "trademarks": [self.candidate], "copyright_assets": [], "enforcement": []}
        self.evidence["collections"].setdefault("trademarks", []).append({"evidence_id": "E1", "payload": copy.deepcopy(self.candidate)})
        self.ledger = empty_materiality_ledger(self.task["task_id"], task=self.task)
        self.save()
        self.plan = generate_plan(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def save(self):
        atomic_write_json(self.path / "task.json", self.task)
        atomic_write_json(self.path / "normalized-candidates.json", self.candidates)
        atomic_write_json(self.path / "evidence.json", self.evidence)
        atomic_write_json(self.path / "materiality-annotations.json", self.ledger)

    def annotate(self, decision="selected", scenario="product_entry", **extra):
        collection = "patents" if self.candidate["right_type"] in {"patent", "design"} else "trademarks"
        row = make_annotation(self.task, collection, self.candidate,
            {"annotation_id": "D" + str(len(self.ledger["annotations"]) + 1), "decision": decision,
             "scenario_id": scenario, "reason": "Synthetic record comparison", "reviewer": "offline-agent",
             "annotated_at": "2026-01-01T00:00:00Z", "evidence_refs": ["E1"],
             "reading_level": "registry_record", "basis_summary": "Mark and goods read from fixture",
             "reopen_conditions": ["New protected goods or ownership evidence"], **extra}, evidence=self.evidence)
        self.ledger["annotations"].append(row)
        self.save()
        return effective_decision(self.task, self.ledger, collection, self.candidate, scenario, "US", evidence=self.evidence)

    def test_shared_initial_queries_do_not_duplicate_and_brand_scope_is_tm_only(self):
        rows = [(p, row) for p, values in self.plan["queries"].items() for row in values]
        self.assertTrue(rows)
        self.assertEqual(len(rows), len({row["query_id"] for _, row in rows}))
        for provider, row in rows:
            self.assertIsNone(scenario_dispatch_block(self.task, self.plan, provider, row, self.candidates, self.ledger, self.evidence))
            self.assertIn("evidence_obligation_id", row)
            if row["right_type"] == "patent":
                self.assertEqual([b["scenario_id"] for b in row["scenario_bindings"]], ["product_entry"])
        tm = next(row for p, row in rows if p == "uspto_tmsearch_browser")
        self.assertEqual({b["scenario_id"] for b in tm["scenario_bindings"]}, {"product_entry", "brand_reuse"})

    def test_material_or_exact_brand_cannot_schedule_deep_verification(self):
        append_candidate_actions(self.path, self.task, self.candidates)
        self.assertFalse(load_json(self.path / "search-plan.json")["queries"].get("uspto_tsdr"))
        self.annotate(scenario="brand_reuse")
        append_candidate_actions(self.path, self.task, self.candidates)
        planned = load_json(self.path / "search-plan.json")
        self.assertEqual(len(planned["queries"]["uspto_tsdr"]), 1)
        row = planned["queries"]["uspto_tsdr"][0]
        self.assertEqual(row["scenario_id"], "brand_reuse")
        self.assertEqual(row["triage_jurisdiction"], "US")
        self.assertIsNone(scenario_dispatch_block_from_dir(self.path, "uspto_tsdr", row))

    def prepare_asset_candidate(self, right_type, *, specialty=True):
        from record_asset_provenance import inventory_identity_sha256
        from workflow_v24 import build_coverage_requirements_v24
        if not specialty:
            self.task.pop("specialty_workflow_revision", None)
            self.plan.pop("specialty_workflow_revision", None)
            self.task["coverage_requirements"] = build_coverage_requirements_v24(
                self.task["target_jurisdictions"], screening_revision=self.task.get("screening_revision"))
        self.task["product"]["assets"] = [{"asset_id": "shape", "usage": "product_configuration",
            "right_types": [right_type], "scenario_ids": ["product_entry"],
            "scope_reasoning": "Observed product configuration is within the fixture scenario", "evidence_refs": ["E1"]}]
        self.task["product"]["asset_scope_review"] = {"status": "reviewed", "reviewer": "offline-agent",
            "reasoning": "Complete observed asset inventory reviewed", "evidence_refs": ["E1"],
            "inventory_identity_sha256": inventory_identity_sha256(self.task, right_type)}
        self.task["product"]["analysis"]["identity_sha256"] = product_identity_digest(self.task["product"], task=self.task)
        self.candidate = {"candidate_id": "SYNTHETIC-ASSET", "right_type": right_type, "jurisdiction": "US",
            "title": "Observed source expression", "evidence_refs": ["E1"]}
        self.candidates["trademarks"] = []
        self.candidates["copyright_assets"] = [self.candidate]
        self.evidence["collections"]["trademarks"][0]["payload"] = copy.deepcopy(self.candidate)
        decision = make_annotation(self.task, "copyright_assets", self.candidate, {
            "annotation_id": "D-ASSET", "decision": "selected", "scenario_id": "product_entry",
            "reason": "Specific source expression corresponds to the adopted asset", "reviewer": "offline-agent",
            "annotated_at": "2026-01-01T00:00:00Z", "evidence_refs": ["E1"], "reading_level": "full_document",
            "basis_summary": "Retained original and observed configuration compared", "reopen_conditions": ["Different proposed asset"]}, evidence=self.evidence)
        self.ledger["annotations"] = [decision]
        self.save()
        atomic_write_json(self.path / "search-plan.json", self.plan)

    def test_selected_specialty_candidates_reach_each_bound_agent_step(self):
        from record_asset_provenance import asset_scope, agent_work_queue, INVESTIGATION_STEPS
        # Run both rights through the real planner, reconciliation and Agent
        # queue. Checking generated dictionaries alone missed the old immediate
        # PROVENANCE_SCOPE_STALE cancellation.
        for right_type in ("copyright", "trade_dress"):
            with self.subTest(right_type=right_type):
                self.prepare_asset_candidate(right_type)
                append_candidate_actions(self.path, self.task, self.candidates)
                plan = load_json(self.path / "search-plan.json")
                rows = [row for row in plan["queries"]["asset_provenance"] if row.get("candidate_id") == "SYNTHETIC-ASSET"]
                self.assertEqual({row["search_dimension"] for row in rows}, set(INVESTIGATION_STEPS[right_type]))
                self.assertEqual(len(rows), len(INVESTIGATION_STEPS[right_type]))
                scope = asset_scope(self.task, "product_entry", right_type)
                self.assertTrue(scope["inventory_reviewed"])
                for row in rows:
                    self.assertEqual(row["asset_scope_sha256"], scope["scope_sha256"])
                    self.assertEqual(row["scenario_id"], "product_entry")
                    self.assertEqual(row["triage_candidate_id"], "SYNTHETIC-ASSET")
                    self.assertEqual(row["triage_decision_id"], "D-ASSET")
                    self.assertEqual(row["action_purpose"], "provenance")
                    self.assertIsNone(validated_query_cancellation(self.task, plan, row))
                    self.assertIsNone(scenario_dispatch_block_from_dir(self.path, "asset_provenance", row))
                queued = {item["query_id"]: item for item in agent_work_queue(self.path)["work"]}
                for row in rows:
                    self.assertEqual(queued[row["query_id"]]["step"], row["search_dimension"])
                    self.assertEqual(queued[row["query_id"]]["status"], "public_investigation_pending")
                    self.assertEqual(queued[row["query_id"]]["asset_ids"], ["shape"])

    def test_selected_asset_without_specialty_marker_keeps_legacy_action(self):
        self.prepare_asset_candidate("copyright", specialty=False)
        append_candidate_actions(self.path, self.task, self.candidates)
        plan = load_json(self.path / "search-plan.json")
        rows = [row for row in plan["queries"]["asset_provenance"] if row.get("candidate_id") == "SYNTHETIC-ASSET"]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["search_dimension"], "provenance")
        self.assertEqual(row["q"], "candidate-source:SYNTHETIC-ASSET")
        self.assertNotIn("asset_scope_sha256", row)
        self.assertIsNone(scenario_dispatch_block_from_dir(self.path, "asset_provenance", row))

    def test_selected_provenance_counts_as_verification_not_initial_retrieval(self):
        for right_type in ("copyright", "trade_dress"):
            with self.subTest(right_type=right_type):
                self.prepare_asset_candidate(right_type)
                self.plan = generate_plan(self.path, expand=True)
                append_candidate_actions(self.path, self.task, self.candidates)
                plan = load_json(self.path / "search-plan.json")
                selected_steps = [row for row in plan["queries"]["asset_provenance"]
                                  if row.get("triage_candidate_id") == "SYNTHETIC-ASSET"]
                self.assertTrue(selected_steps)
                # Isolate classification of genuine planned obligations. This
                # mock represents completed initial investigations, not a
                # shortcut through source/receipt validation in production.
                def completed_initial(evidence, candidates, plan, provider, query, task, **kwargs):
                    complete = not query.get("triage_candidate_id")
                    return {"query_id": query["query_id"], "provider": provider,
                            "complete": complete, "retrieval_complete": complete,
                            "triage_complete": True, "gap": "" if complete else "QUERY_NOT_COMPLETED"}
                with patch("assessment_v24.query_coverage", side_effect=completed_initial):
                    scopes = coverage_by_scope(self.task, self.evidence, self.candidates, plan, ledger=self.ledger)
                scope = next(row for row in scopes if row["scenario_id"] == "product_entry" and row["right_type"] == right_type)
                self.assertEqual(scope["retrieval_status"], "complete")
                self.assertEqual(scope["verification_status"], "incomplete")
                self.assertNotEqual(scope["status"], "满足已定义要求")
                self.assertTrue(all("OBLIGATION_INCOMPLETE:" + row["evidence_obligation_id"] in scope["gaps"] for row in selected_steps))
                with patch("assessment_v24.query_coverage", side_effect=lambda evidence, candidates, plan, provider, query, task, **kwargs:
                           {"query_id": query["query_id"], "provider": provider, "complete": True,
                            "retrieval_complete": True, "triage_complete": True, "gap": ""}):
                    finished = next(row for row in coverage_by_scope(self.task, self.evidence, self.candidates, plan,
                                    ledger=self.ledger) if row["scenario_id"] == "product_entry" and row["right_type"] == right_type)
                self.assertEqual(finished["retrieval_status"], "complete")
                self.assertEqual(finished["verification_status"], "complete")
                self.assertEqual(finished["status"], "满足已定义要求")

    def test_legacy_provenance_completion_split_is_unchanged(self):
        self.prepare_asset_candidate("copyright", specialty=False)
        append_candidate_actions(self.path, self.task, self.candidates)
        plan = load_json(self.path / "search-plan.json")
        scope = next(row for row in coverage_by_scope(self.task, self.evidence, self.candidates, plan,
                     ledger=self.ledger) if row["scenario_id"] == "product_entry" and row["right_type"] == "copyright")
        self.assertEqual(scope["retrieval_status"], "incomplete")
        self.assertEqual(scope["verification_status"], "complete")
        self.assertNotEqual(scope["status"], "满足已定义要求")

    def test_us_figurative_description_axis_requires_target_language(self):
        requirement = next(item for item in self.task["coverage_requirements"]
            if item["jurisdiction"] == "US" and item["right_type"] == "trademark_figurative" and item["phase"] == "official_recall")
        self.task["coverage_requirements"] = [requirement]
        self.candidates["trademarks"] = []
        for language in ("zh", "en"):
            with self.subTest(language=language):
                row = entry("uspto_tmsearch_browser", "trademark_recall", "US",
                    {"q": "stylized lettering", "filters": {"field": "mark_description", "language": language}},
                    required=False, right_type="trademark_figurative", requirement_ids=[requirement["requirement_id"]],
                    derived_from=["product.mark_inventory[0]"])
                row.update(required_for="low_risk", execute_by_default=True, search_dimension="description",
                           search_language=language, execution_phase="initial")
                row = bind_scenario_action(self.task, "uspto_tmsearch_browser", row, purpose="recall", obligation_key="description")
                plan = {**self.plan, "queries": {"uspto_tmsearch_browser": [row]}}
                scopes = coverage_by_scope(self.task, self.evidence, self.candidates, plan, ledger=self.ledger)
                self.assertTrue(scopes)
                for scope in scopes:
                    self.assertEqual(any("LOCAL_LANGUAGE_MISSING" in gap for gap in scope["gaps"]), language != "en")
                    # Correct language alone never pretends the query ran.
                    self.assertEqual(scope["retrieval_status"], "incomplete")

    def test_new_figurative_contract_rejects_legacy_word_rows_without_false_completion(self):
        row = entry("uspto_tmsearch_browser", "trademark_recall", "US",
            {"q": "TEST", "filters": {"field": "brand", "language": "en"}}, required=False,
            right_type="trademark_figurative", requirement_ids=["COV-US-TRADEMARK_FIGURATIVE-RECALL"],
            derived_from=["product.brand"])
        row.update(required_for="low_risk", execute_by_default=True, search_dimension="text",
                   search_language="en", execution_phase="initial")
        row = bind_scenario_action(self.task, "uspto_tmsearch_browser", row, purpose="recall", obligation_key="legacy-word")
        plan = {**self.plan, "queries": {"uspto_tmsearch_browser": [row]}}
        self.assertEqual(scenario_dispatch_block(self.task, plan, "uspto_tmsearch_browser", row,
            self.candidates, self.ledger, self.evidence)["code"], "FIGURATIVE_QUERY_FIELD_UNSUPPORTED")
        scopes = [scope for scope in coverage_by_scope(self.task, self.evidence, self.candidates, plan,
            ledger=self.ledger) if scope["right_type"] == "trademark_figurative"]
        self.assertTrue(scopes)
        self.assertTrue(all(scope["retrieval_status"] == "incomplete" and
                            any("AXIS_MISSING:description" in gap for gap in scope["gaps"]) for scope in scopes))
        legacy = copy.deepcopy(self.task)
        legacy.pop("specialty_workflow_revision")
        self.assertIsNone(scenario_dispatch_block(legacy, plan, "uspto_tmsearch_browser", row,
            self.candidates, self.ledger, self.evidence))

    def test_new_decision_cancels_old_actions_without_rewriting_rows(self):
        self.annotate()
        append_candidate_actions(self.path, self.task, self.candidates)
        old = load_json(self.path / "search-plan.json")["queries"]["uspto_tsdr"][0]
        digest = sha256_json(old)
        self.annotate("not_selected")
        append_candidate_actions(self.path, self.task, self.candidates)
        plan = load_json(self.path / "search-plan.json")
        self.assertEqual(sha256_json(plan["queries"]["uspto_tsdr"][0]), digest)
        self.assertIsNotNone(validated_query_cancellation(self.task, plan, old))
        self.assertIsNotNone(scenario_dispatch_block_from_dir(self.path, "uspto_tsdr", old))
        from run_browser_plan import execute_plan
        with patch("run_browser_plan.load_skill_config", return_value={}):
            output = execute_plan(self.path, query_id_filter=old["query_id"], runner=lambda *_args, **_kwargs: self.fail("Stale action reached browser"))
        self.assertEqual(output["queries"][0]["status"], "cancelled")

    def test_direct_guard_rejects_cancelled_and_rehashed_scope_tampering(self):
        self.annotate()
        append_candidate_actions(self.path, self.task, self.candidates)
        plan = load_json(self.path / "search-plan.json")
        row = plan["queries"]["uspto_tsdr"][0]
        plan.setdefault("execution_dispositions", []).append({"query_id": row["query_id"], "plan_entry_sha256": sha256_json(row), "status": "cancelled", "reason": "explicit bounded pause"})
        atomic_write_json(self.path / "search-plan.json", plan)
        self.assertEqual(scenario_dispatch_block_from_dir(self.path, "uspto_tsdr", row)["code"], "SCENARIO_ACTION_CANCELLED")
        row["action_purpose"] = "tampered"
        self.assertEqual(scenario_dispatch_block(self.task, plan, "uspto_tsdr", row, self.candidates, self.ledger, self.evidence)["code"], "SCENARIO_QUERY_IDENTITY_MISMATCH")

    def test_recomputed_query_id_cannot_remove_required_candidate_authority(self):
        decision = self.annotate()
        append_candidate_actions(self.path, self.task, self.candidates)
        plan = load_json(self.path / "search-plan.json")
        row = plan["queries"]["uspto_tsdr"][0]
        for key in list(row):
            if key.startswith("triage_") or key in {"candidate_id", "scenario_id", "scenario_sha256"}:
                row.pop(key)
        row["scenario_bindings"] = self.plan["queries"]["uspto_tmsearch_browser"][0]["scenario_bindings"]
        identity = {key: value for key, value in row.items() if key not in PLAN_META_KEYS or key in SCENARIO_META_KEYS}
        identity["right_type"] = row["right_type"]
        row["query_id"] = query_identity("uspto_tsdr", row["operation"], row["jurisdiction"], row["q"], identity)
        self.assertEqual(scenario_dispatch_block(self.task, plan, "uspto_tsdr", row, self.candidates, self.ledger, self.evidence)["code"], "TRIAGE_ACTION_BINDING_REQUIRED")

    def test_candidate_owner_expansion_requires_current_selected_country_and_scenario(self):
        self.candidate = {"candidate_id": "P1", "normalization_key": "US11111111B2", "publication_number": "US11111111B2",
                          "jurisdiction": "US", "right_type": "patent", "owner": "Test Owner", "title": "Synthetic strap",
                          "material": True, "evidence_refs": ["E1"]}
        self.candidates["patents"], self.candidates["trademarks"] = [self.candidate], []
        self.evidence["collections"]["trademarks"][0]["payload"] = copy.deepcopy(self.candidate)
        self.save()
        generate_plan(self.path, expand=True)
        before = load_json(self.path / "search-plan.json")
        self.assertFalse(any(row.get("triage_candidate_id") for rows in before["queries"].values() for row in rows))
        self.annotate()
        expanded = generate_plan(self.path, expand=True)
        rows = [row for values in expanded["queries"].values() for row in values if row.get("triage_candidate_id")]
        self.assertTrue(rows)
        self.assertTrue(all(row["scenario_id"] == "product_entry" and row["triage_jurisdiction"] == "US" and row["right_type"] == "patent" for row in rows))
        self.assertEqual({row["query_id"]: sha256_json(row) for values in before["queries"].values() for row in values},
                         {row["query_id"]: sha256_json(row) for values in expanded["queries"].values() for row in values if not row.get("triage_candidate_id")})

    def test_api_scheduler_never_dispatches_stale_scenario_actions(self):
        from runtime_v24 import execute_api_plan
        row = copy.deepcopy(next(iter(self.plan["queries"]["epo_ops"])))
        row["scenario_bindings"][0]["scenario_sha256"] = "0" * 64
        plan = {**self.plan, "queries": {"epo_ops": [row]}}
        atomic_write_json(self.path / "search-plan.json", plan)
        with patch("runtime_v24.credential", return_value=""), patch("runtime_v24.subprocess.run") as network:
            output = execute_api_plan(self.path)
        network.assert_not_called()
        self.assertEqual(output["results"][0]["status"], "cancelled")
        self.assertEqual(load_json(self.path / "evidence.json")["source_runs"], self.evidence["source_runs"])

    def test_needs_info_has_one_bound_lookup_and_never_auto_promotes(self):
        params = {"q": "88418732", "serial_number": "88418732", "candidate_id": self.candidate["candidate_id"], "mode": "agent", "strategy": "record_number"}
        self.annotate("needs_info", missing_information=["Goods scope required"], next_actions=[
            {"action_id": "N1", "kind": "source_lookup", "purpose": "read_goods", "provider": "uspto_tsdr", "operation": "candidate_verification", "params": params, "max_attempts": 1,
             "required_facts": ["goods_services"], "reading_scope": {"level": "goods_services"}},
            {"action_id": "N2", "kind": "user_information", "purpose": "use_context", "question": "Will this mark be used?"}])
        append_candidate_actions(self.path, self.task, self.candidates)
        plan = load_json(self.path / "search-plan.json")
        row = plan["queries"]["uspto_tsdr"][0]
        self.assertEqual(row["action_purpose"], "needs_info:read_goods")
        self.assertIsNone(scenario_dispatch_block_from_dir(self.path, "uspto_tsdr", row))
        self.evidence["source_runs"].append({"provider": "uspto_tsdr", "query_id": row["query_id"], "plan_entry_sha256": sha256_json(row), "status": "failed", "submission_state": "submitted"})
        self.save()
        self.assertEqual(scenario_dispatch_block_from_dir(self.path, "uspto_tsdr", row)["code"], "TRIAGE_BOUNDED_ACTION_ALREADY_ATTEMPTED")
        self.assertTrue(plan["triage_action_queue"])

    def test_incomplete_candidate_identifier_is_internal_planning_gap_not_browser_query(self):
        self.annotate("needs_info", missing_information=["Goods scope"], next_actions=[{
            "action_id": "BAD-ID", "kind": "source_lookup", "purpose": "read_goods",
            "provider": "uspto_tsdr", "operation": "candidate_verification",
            "required_facts": ["goods_services"], "reading_scope": {"level": "goods_services"},
            "params": {"q": "88418732", "candidate_id": self.candidate["candidate_id"]}, "max_attempts": 1}])
        append_candidate_actions(self.path, self.task, self.candidates)
        plan = load_json(self.path / "search-plan.json")
        self.assertFalse(plan["queries"].get("uspto_tsdr"))
        self.assertIn("INTERNAL_CANDIDATE_PLAN_CONTRACT_ERROR", str(plan))

    def test_browser_candidate_plan_error_is_not_reported_as_site_access_failure(self):
        from run_browser_plan import run_process
        completed = subprocess.CompletedProcess(["node"], 1, "", "Error: CANDIDATE_PLAN_RECORD_MISMATCH: bad binding")
        with patch("run_browser_plan.subprocess.run", return_value=completed):
            result = run_process(["node"])
        self.assertEqual((result["status"], result["submission_state"], result["phase"]),
                         ("failed", "not_submitted", "validate_plan"))
        self.assertEqual(result["error_code"], "CANDIDATE_PLAN_RECORD_MISMATCH")

    def test_official_audit_separates_hashed_scenario_metadata_from_provider_params(self):
        from finalize_assessment import _verification_plan_binding_matches
        from run_browser_plan import request_params
        self.annotate(scenario="brand_reuse")
        append_candidate_actions(self.path, self.task, self.candidates)
        plan = load_json(self.path / "search-plan.json")
        row = plan["queries"]["uspto_tsdr"][0]
        run = {"request_params": request_params(row), "requirement_ids": row["requirement_ids"],
               "plan_entry_sha256": sha256_json(row), "query": row["q"]}
        observed = {"requirement_ids": row["requirement_ids"], "plan_entry_sha256": sha256_json(row)}
        def matches():
            return _verification_plan_binding_matches(plan, self.candidate, run, observed,
                provider="uspto_tsdr", query_id=row["query_id"], jurisdiction="US",
                right_type="trademark_word", requirement_ids=set(row["requirement_ids"]))
        self.assertTrue(matches())
        run["request_params"]["serial_number"] = "00000000"
        self.assertFalse(matches())
        run["request_params"] = request_params(row)
        row["scenario_sha256"] = "0" * 64
        self.assertFalse(matches())

    def narrow_plan(self):
        self.task["coverage_requirements"] = [{"requirement_id": "REQ", "jurisdiction": "US", "right_type": "trademark_word", "phase": "official_recall",
                                              "required_axes": ["text"], "required_language": "en", "expansion_required": False,
                                              "routes": [{"provider": "uspto_tmsearch_browser", "operation": "trademark_recall"}]}]
        def query(provider, q, obligation):
            row = entry(provider, "trademark_recall", "US", {"q": q}, required=False, right_type="trademark_word", requirement_ids=["REQ"], derived_from=["product.brand"])
            row.update(required_for="low_risk", execute_by_default=True, search_dimension="text", search_language="en", execution_phase="initial")
            return bind_scenario_action(self.task, provider, row, purpose="recall", obligation_key=obligation)
        first, second = query("uspto_tmsearch_browser", "TEST", "same"), query("epo_ops", "TEST", "same")
        plan = {**self.plan, "queries": {"uspto_tmsearch_browser": [first], "epo_ops": [second]}}
        return plan, first, second

    def add_run(self, provider, row, *, status="success", candidates=None, total=None):
        records = [self.candidate] if candidates is None else candidates
        run = {"run_id": "RUN-" + str(len(self.evidence["source_runs"])), "query_id": row["query_id"], "provider": provider,
               "operation": row["operation"], "jurisdiction": row["jurisdiction"], "right_type": row["right_type"],
               "requirement_ids": row["requirement_ids"], "plan_entry_sha256": sha256_json(row), "status": status,
               "metadata": {"search_coverage": {"schema_valid": True, "total_hits": len(records) if total is None else total,
                                                "retrieved_hits": len(records), "truncated": False, "stop_reason": "all_records_read"}}}
        self.evidence["source_runs"].append(run)
        self.evidence["collections"]["trademarks"].append({**run, "evidence_id": "BOUND-" + run["run_id"], "source_run_id": run["run_id"], "payload": {"candidates": copy.deepcopy(records)}})
        if records:
            self.candidate.setdefault("sources", []).append({"query_id": row["query_id"]})

    def test_optional_provider_failure_does_not_override_complete_same_obligation(self):
        plan, first, second = self.narrow_plan()
        self.add_run("uspto_tmsearch_browser", first)
        self.add_run("epo_ops", second, status="access_limited", candidates=[])
        self.annotate("not_selected")
        self.annotate("not_selected", scenario="brand_reuse")
        with patch("finalize_assessment._authoritative_run", return_value=True):
            scopes = coverage_by_scope(self.task, self.evidence, self.candidates, plan, ledger=self.ledger)
        self.assertTrue(all(scope["retrieval_status"] == "complete" for scope in scopes))
        self.assertTrue(all(scope["triage_status"] == "complete" for scope in scopes))
        self.assertTrue(all(not scope["gaps"] for scope in scopes))
        self.candidates["trademarks"] = []
        with patch("finalize_assessment._authoritative_run", return_value=True):
            broken = coverage_by_scope(self.task, self.evidence, self.candidates, plan, ledger=self.ledger)
        self.assertTrue(all(scope["retrieval_status"] == "incomplete" for scope in broken))

    def test_explicit_substitution_binds_both_hashes_and_needs_actual_complete_target(self):
        plan, old, _ = self.narrow_plan()
        new = entry("uspto_tmsearch_browser", "trademark_recall", "US", {"q": "TEST replacement"}, required=False, right_type="trademark_word", requirement_ids=["REQ"], derived_from=["product.brand"])
        new.update(required_for="low_risk", execute_by_default=True, search_dimension="text", search_language="en", execution_phase="initial")
        new = bind_scenario_action(self.task, "uspto_tmsearch_browser", new, purpose="recall", obligation_key="replacement")
        plan["queries"] = {"uspto_tmsearch_browser": [old, new]}
        scope = next(binding for binding in old["scenario_bindings"] if binding["scenario_id"] == "product_entry")
        substitution = {"old_query_id": old["query_id"], "old_plan_entry_sha256": sha256_json(old), "new_query_id": new["query_id"],
                        "new_plan_entry_sha256": sha256_json(new), "jurisdiction": "US", "right_type": "trademark_word", **scope,
                        "action_purpose": "recall", "reason": "Explicit equivalent local expression", "reviewer": "offline-agent"}
        plan["action_substitutions"] = [substitution]
        self.assertIsNotNone(validated_query_substitution(self.task, plan, old))
        with patch("finalize_assessment._authoritative_run", return_value=True):
            before = coverage_by_scope(self.task, self.evidence, self.candidates, plan, ledger=self.ledger)
        self.assertTrue(before[0]["gaps"])
        self.add_run("uspto_tmsearch_browser", new, status="no_result", candidates=[])
        self.candidates["trademarks"] = []
        with patch("finalize_assessment._authoritative_run", return_value=True):
            after = coverage_by_scope(self.task, self.evidence, self.candidates, plan, ledger=self.ledger)
        self.assertFalse(next(scope for scope in after if scope["scenario_id"] == "product_entry")["gaps"])
        self.assertTrue(next(scope for scope in after if scope["scenario_id"] == "brand_reuse")["gaps"])
        substitution["new_plan_entry_sha256"] = "0" * 64
        self.assertIsNone(validated_query_substitution(self.task, plan, old))
        substitution["new_plan_entry_sha256"] = sha256_json(new)
        plan["action_substitutions"].append({**substitution, "old_query_id": new["query_id"], "old_plan_entry_sha256": sha256_json(new), "new_query_id": old["query_id"], "new_plan_entry_sha256": sha256_json(old)})
        self.assertIsNone(validated_query_substitution(self.task, plan, old))

    def test_paginated_retrieval_and_light_triage_are_independent(self):
        plan, seed, _ = self.narrow_plan()
        first = bind_scenario_action(self.task, "uspto_tmsearch_browser", {**seed, "range": "1-1"}, purpose="recall", obligation_key="pages")
        second = bind_scenario_action(self.task, "uspto_tmsearch_browser", {**seed, "range": "2-2"}, purpose="recall", obligation_key="pages")
        plan["queries"] = {"uspto_tmsearch_browser": [first, second]}
        other = {**copy.deepcopy(self.candidate), "candidate_id": "C2", "normalization_key": "US:trademark_word:99999999", "serial_number": "99999999"}
        self.candidates["trademarks"].append(other)
        self.add_run("uspto_tmsearch_browser", first, total=2)
        self.add_run("uspto_tmsearch_browser", second, candidates=[other], total=2)
        other["sources"] = [{"query_id": second["query_id"]}]
        self.candidate["sources"] = [{"query_id": first["query_id"]}]
        for run in self.evidence["source_runs"]:
            run["metadata"]["search_coverage"]["truncated"] = True
        with patch("finalize_assessment._authoritative_run", return_value=True):
            scopes = coverage_by_scope(self.task, self.evidence, self.candidates, plan, ledger=self.ledger)
        self.assertTrue(all(scope["retrieval_status"] == "complete" for scope in scopes))
        self.assertTrue(all(scope["triage_status"] == "incomplete" for scope in scopes))
        self.candidates["trademarks"].pop()
        with patch("finalize_assessment._authoritative_run", return_value=True):
            broken = coverage_by_scope(self.task, self.evidence, self.candidates, plan, ledger=self.ledger)
        self.assertTrue(all(scope["retrieval_status"] == "incomplete" for scope in broken))

    def test_published_document_content_never_satisfies_current_verification(self):
        row = {"query_id": "DOC", "operation": "document_retrieval", "jurisdiction": "EP", "right_type": "patent",
               "q": "EP1111111B1", "document": "EP1111111B1", "candidate_id": "P1", "requirement_ids": [], "action_purpose": "document_content"}
        plan = {"queries": {"epo_publication_server": [row]}}
        record = {"candidate_id": "P1", "publication_number": "EP1111111B1", "authority_scope": "published_document_only",
                  "document_identity_match": True, "claims": [{"text": "Synthetic claim"}], "authoritative_for_final_rating": False}
        self.add_run("epo_publication_server", row, candidates=[record])
        self.evidence["source_runs"][-1]["authoritative_for_final_rating"] = False
        self.assertTrue(_scenario_action_complete(self.evidence, plan, "epo_publication_server", row))
        row["action_purpose"] = "official_verification"
        self.assertFalse(_scenario_action_complete(self.evidence, plan, "epo_publication_server", row))


if __name__ == "__main__":
    unittest.main()
