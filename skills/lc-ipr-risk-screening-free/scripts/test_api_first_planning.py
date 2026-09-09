"""Synthetic, offline plan/dispatch tests; none are real discovery evidence."""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from common import atomic_write_json, load_json, sha256_json, sha256_file, serper_free_enhancement, serpapi_free_enhancement
from workflow_v24 import generate_plan, scenario_dispatch_block_from_dir, assert_recall_planning_contract, product_identity_digest
from api_first_planning import (REVISION, append_followup, dispatch_block, google_query, make_row,
    next_work_entries, triage_digest)
import test_scenario_planning as scenario_fixture


class ApiFirstPlanningTests(unittest.TestCase):
    def setUp(self):
        scenario_fixture.ScenarioPlanningTests.setUp(self)
        self.task["retrieval_workflow_revision"] = REVISION
        self.task["serper_free_enhancement"] = serper_free_enhancement(True, REVISION)
        self.task["serpapi_free_enhancement"] = serpapi_free_enhancement(False, REVISION)
        from common import load_skill_config
        self.task["retrieval_policy"] = deepcopy(load_skill_config()["api_first"])
        self.regenerate()

    tearDown = scenario_fixture.ScenarioPlanningTests.tearDown
    save = scenario_fixture.ScenarioPlanningTests.save

    def regenerate(self):
        atomic_write_json(self.path / "task.json", self.task)
        (self.path / "search-plan.json").unlink(missing_ok=True)
        self.plan = generate_plan(self.path)
        return self.plan

    def primary(self):
        return self.plan["queries"]["serper_patents"][0]

    def source(self, row=None, *, status="no_result"):
        row = row or self.primary()
        self.evidence = load_json(self.path / "evidence.json")
        raw = self.path / ("source-" + str(len(self.evidence["source_runs"])) + ".json")
        atomic_write_json(raw, {"fixture_only": True, "organic": []})
        identity = "UNIT-RUN-" + str(len(self.evidence["source_runs"]))
        provider = next(p for p, rows in self.plan["queries"].items() if row in rows)
        record = {"run_id": identity, "provider": provider, "query_id": row["query_id"], "plan_entry_sha256": sha256_json(row),
            "status": status, "submission_state": "submitted", "raw_paths": [raw.name], "payload_digest": sha256_file(raw),
            "source_environment": "unit_test_only", **{k: row[k] for k in ("operation", "jurisdiction", "right_type", "requirement_ids")},
            **({"error_code": "PROVIDER_TIMEOUT"} if status == "failed" else {})}
        self.evidence["source_runs"].append(record)
        self.evidence["collections"].setdefault("patents", []).append({"evidence_id": "EV-" + identity,
            "source_run_id": identity, **{k: record[k] for k in ("provider", "query_id", "operation", "jurisdiction", "right_type", "requirement_ids", "plan_entry_sha256")},
            "payload": {"candidates": [], "fixture_only": True}})
        atomic_write_json(self.path / "evidence.json", self.evidence)
        return record

    def request(self, parent=None, *, role="refinement", provider="serper_patents", value="strap fastening"):
        parent = parent or self.primary()
        run = self.source(parent)
        return {"parent_query_id": parent["query_id"], "role": role, "provider": provider,
            "term": {"kind": "structural_feature", "value": value, "language": "en", "derived_from": parent["derived_from"][0]},
            "source_run_id": run["run_id"], "reason_code": "zero_results", "reason": "Synthetic empty response supports a new structural expression",
            "reviewer": "unit-agent", "evidence_ids": ["EV-" + run["run_id"]],
            "triage_digest": triage_digest(self.task, self.evidence, self.candidates, self.ledger, query_id=parent["query_id"])}

    def reload(self):
        self.task = load_json(self.path / "task.json")
        self.plan = load_json(self.path / "search-plan.json")

    def test_initial_api_only_plus_specialties_and_bounded_contract(self):
        self.assertNotIn("uspto_patent_browser", self.plan["queries"])
        self.assertNotIn("uspto_tmsearch_browser", self.plan["queries"])
        self.assertIn("asset_provenance", self.plan["queries"])
        rows = [r for p, values in self.plan["queries"].items() if p.startswith("serper") for r in values]
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(row["execution_phase"], "discovery")
            self.assertEqual(row["num"], 10)
            self.assertEqual(row["discovery_scope"]["max_pages"], 1)
            self.assertEqual(row["required_for"], "discovery_only")
            self.assertFalse(row["authoritative_for_final_rating"])
            self.assertTrue(row["requirement_ids"])
            provider = next(p for p, values in self.plan["queries"].items() if row in values)
            self.assertIsNone(scenario_dispatch_block_from_dir(self.path, provider, row))

    def test_four_structure_clues_are_all_preserved_or_explicitly_deferred(self):
        self.task["query_terms"] = [{"kind": "structural_feature", "value": text, "language": "en", "derived_from": f"product.structure[{i}]"}
            for i, text in enumerate(("push button", "layered ring", "rectangular openings", "rotating body"))]
        self.task["product"]["structure"] = [t["value"] for t in self.task["query_terms"]]
        self.task["product"]["analysis"]["identity_sha256"] = product_identity_digest(self.task["product"], task=self.task)
        self.regenerate()
        patent_sources = {source for rows in self.plan["queries"].values() for r in rows if r["right_type"] == "patent" for source in r["derived_from"]}
        self.assertTrue({t["derived_from"] for t in self.task["query_terms"]} <= patent_sources)

    def test_budget_shared_between_endpoints_and_explicit_gaps(self):
        self.task["serper_free_enhancement"]["max_queries_per_task"] = 2
        self.regenerate()
        self.assertEqual(sum(len(rows) for p, rows in self.plan["queries"].items() if p.startswith("serper_")), 2)
        self.assertTrue(any(g["code"] == "API_DISCOVERY_BUDGET_EXHAUSTED" for g in self.plan["planning_gaps"]))
        entries = next_work_entries(self.task, self.plan, self.evidence, self.candidates, self.ledger)
        self.assertTrue(any(e["reason"] == "API_DISCOVERY_BUDGET_EXHAUSTED" and e["state"] == "blocked" for e in entries))

    def test_country_round_robin_prevents_first_country_spending_every_slot(self):
        from workflow_v24 import build_coverage_requirements_v24
        self.task["target_jurisdictions"] = ["US", "GB", "DE"]
        self.task["coverage_requirements"] = build_coverage_requirements_v24(["US", "GB", "DE"], screening_revision="recall-integrity-v1", specialty_workflow_revision="asset-scope-v1")
        self.task["query_terms"].append({"kind": "structural_feature", "value": "Riemen Öffnungen", "language": "de", "derived_from": "product.structure[0]"})
        self.task["serper_free_enhancement"]["max_queries_per_task"] = 3
        self.regenerate()
        self.assertEqual({r["jurisdiction"] for r in self.plan["queries"]["serper_patents"]}, {"US", "GB", "DE"})

    def test_google_adapter_does_not_send_pps_syntax_or_and_with_and(self):
        self.assertEqual(google_query({"value": 'press AND (spin OR rotate) NOT motor', "strategy": "boolean"}), "press ( spin OR rotate ) -motor")
        for value in ("press AND WITH AND toy", "US1234567.PN.", "press AND NOT (motor OR battery)"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                google_query({"value": value, "strategy": "boolean"})

    def test_same_google_upstream_is_not_independent_source(self):
        term = self.task["query_terms"][0]
        a = make_row(self.task, "serper_patents", term, "US", "patent", self.primary()["requirement_ids"])
        b = make_row(self.task, "serpapi_google_patents", term, "US", "patent", self.primary()["requirement_ids"])
        self.assertEqual(a["source_index"], b["source_index"])

    def test_policy_change_is_stale_and_plan_is_append_only(self):
        before = deepcopy(self.plan["queries"])
        self.assertEqual(generate_plan(self.path, expand=True)["queries"], before)
        self.task["retrieval_policy"]["browser_fallback_max_candidates"] = 49
        atomic_write_json(self.path / "task.json", self.task)
        with self.assertRaisesRegex(ValueError, "RETRIEVAL_POLICY_CHANGED"):
            generate_plan(self.path, expand=True)
        self.assertEqual(scenario_dispatch_block_from_dir(self.path, "serper_patents", self.primary())["code"], "API_FIRST_RETRIEVAL_POLICY_CHANGED")

    def test_followup_requires_real_parent_run_before_any_plan_write(self):
        before_task = (self.path / "task.json").read_bytes()
        before_plan = (self.path / "search-plan.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "SOURCE_RUN_REQUIRED"):
            append_followup(self.path, {"parent_query_id": self.primary()["query_id"], "role": "refinement", "provider": "serper_patents",
                "term": {"kind": "structural_feature", "value": "changed", "language": "en", "derived_from": "product.structure[0]"}})
        self.assertEqual((self.path / "task.json").read_bytes(), before_task)
        self.assertEqual((self.path / "search-plan.json").read_bytes(), before_plan)

    def test_two_refinement_rounds_then_hard_stop(self):
        parent = self.primary()
        for i in (1, 2):
            new = append_followup(self.path, self.request(parent, value=f"strap fastening {i}"))
            self.reload()
            self.assertEqual(new["refinement_round"], i)
            self.assertEqual(new["discovery_intent_id"], parent["discovery_intent_id"])
            self.assertEqual(new["parent_plan_entry_sha256"], sha256_json(parent))
            self.assertIsNone(scenario_dispatch_block_from_dir(self.path, "serper_patents", new))
            parent = new
        with self.assertRaisesRegex(ValueError, "ROUND_LIMIT"):
            append_followup(self.path, self.request(parent, value="strap fastening three"))

    def test_browser_fallback_limited_and_requires_api_review(self):
        new = append_followup(self.path, self.request(role="browser_fallback", provider="uspto_patent_browser"))
        self.reload()
        self.assertEqual(new["execution_phase"], "discovery_fallback")
        self.assertEqual(new["discovery_scope"]["max_candidates"], 50)
        self.assertEqual(new["discovery_scope"]["max_pages"], 8)
        self.assertIsNone(scenario_dispatch_block_from_dir(self.path, "uspto_patent_browser", new))
        self.task["discovery_followups"] = []
        atomic_write_json(self.path / "task.json", self.task)
        self.assertEqual(scenario_dispatch_block_from_dir(self.path, "uspto_patent_browser", new)["code"], "API_DISCOVERY_FOLLOWUP_DECISION_REQUIRED")

    def test_source_file_tampering_rejects_exact_query_id_dispatch(self):
        req = self.request(role="browser_fallback", provider="uspto_patent_browser")
        new = append_followup(self.path, req)
        self.reload()
        run = next(r for r in self.evidence["source_runs"] if r["run_id"] == req["source_run_id"])
        (self.path / run["raw_paths"][0]).write_text("changed")
        self.assertEqual(scenario_dispatch_block_from_dir(self.path, "uspto_patent_browser", new)["code"], "API_DISCOVERY_SOURCE_FILES_INVALID")

    def test_scope_mismatch_or_unreviewed_parent_cannot_authorize_followup(self):
        req = self.request()
        req["triage_digest"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "TRIAGE_CHANGED"):
            append_followup(self.path, req)

    def test_no_discovery_result_closes_old_official_scope(self):
        from assessment_v24 import scenario_coverage_by_scope
        self.source()
        coverage = scenario_coverage_by_scope(self.task, self.evidence, self.candidates, self.plan, ledger=self.ledger)
        patents = [r for r in coverage if r["right_type"] == "patent"]
        self.assertTrue(patents)
        self.assertTrue(any("AXIS_MISSING" in gap for r in patents for gap in r["gaps"]))

    def test_google_native_country_cpc_and_unicode_semantics(self):
        from api_first_planning import provider_params
        cpc = {"kind": "cpc", "value": "A63H1/00", "strategy": "boolean"}
        self.assertEqual(provider_params("serper_patents", cpc, "US", "patent")["q"], "(cpc:A63H1/00) country:US")
        self.assertEqual(provider_params("serper_patents", cpc, "EU", "patent")["gl"], "fr")
        self.assertEqual(google_query({"kind": "product", "value": "Riemen AND Öffnungen NOT NOT Knopf", "strategy": "boolean"}), "Riemen Öffnungen Knopf")
        with self.assertRaisesRegex(ValueError, "CLASSIFICATION_UNSUPPORTED"):
            google_query({"kind": "uspc", "value": "D21/462", "strategy": "boolean"})

    def test_shared_reserve_does_not_silently_promote_backup(self):
        self.task["serpapi_free_enhancement"] = serpapi_free_enhancement(True, REVISION)
        self.task["query_terms"] += [{"kind": "structural_feature", "value": f"bounded clue {i}",
            "derived_from": "product.structure[0]", "language": "en"} for i in range(35)]
        self.regenerate()
        self.assertEqual(sum(len(rows) for p, rows in self.plan["queries"].items() if p.startswith("serper_")), 23)
        self.assertNotIn("serpapi_google_patents", self.plan["queries"])
        self.assertTrue(any(g["code"] == "API_DISCOVERY_BUDGET_RESERVED_FOR_FOLLOWUP" for g in self.plan["planning_gaps"]))

    def test_brand_inventory_does_not_fund_product_copyright_queries(self):
        self.task["query_terms"].append({"kind": "brand", "value": "Visual Mark", "language": "en", "derived_from": "product.mark_inventory[0]"})
        self.regenerate()
        self.assertFalse(any("Visual Mark" in r.get("q", "") for rs in self.plan["queries"].values() for r in rs
            if r["right_type"] in {"copyright", "trade_dress"}))

    def test_empty_normalization_cannot_skip_one_real_card(self):
        from api_first_planning import source_card_state
        run = self.source(status="success")
        card = {"title": "Unreviewed fixture", "publication_number": "US1234567A", "source_record_sha256": "a" * 64}
        self.evidence["collections"]["patents"][-1]["payload"]["candidates"] = [card]
        atomic_write_json(self.path / "evidence.json", self.evidence)
        error, _ = source_card_state(self.task, self.evidence, self.candidates, self.ledger, self.primary(), run)
        self.assertEqual(error, "API_DISCOVERY_MERGE_REQUIRED")
        entries = next_work_entries(self.task, self.plan, self.evidence, self.candidates, self.ledger)
        self.assertTrue(any(e.get("query_id") == self.primary()["query_id"] and e["reason"] == error for e in entries))

    def test_unknown_card_type_requires_identity_review_instead_of_skipping_scope(self):
        from api_first_planning import source_card_state
        run = self.source(status="success")
        card_hash = "a" * 64
        self.evidence["collections"]["patents"][-1]["payload"]["candidates"] = [{"source_record_sha256": card_hash}]
        self.candidates["patents"] = [{"candidate_id": "UNKNOWN-FIXTURE", "right_type": "unknown", "right_type_status": "unresolved",
            "sources": [{"source_record_sha256": card_hash, "source_run_id": run["run_id"], "query_id": self.primary()["query_id"],
                "plan_entry_sha256": sha256_json(self.primary())}]}]
        self.assertEqual(source_card_state(self.task, self.evidence, self.candidates, self.ledger, self.primary(), run)[0],
            "API_DISCOVERY_CARD_IDENTITY_REVIEW_REQUIRED")

    def test_raw_cards_and_payload_hashes_must_match_even_if_count_same(self):
        from api_first_planning import source_files_error
        run = self.source(status="success")
        path = self.path / run["raw_paths"][0]
        atomic_write_json(path, {"organic": [{"title": "actual card"}]})
        run["payload_digest"] = sha256_file(path)
        self.evidence["collections"]["patents"][-1]["payload"]["candidates"] = [{"title": "substituted card"}]
        self.assertEqual(source_files_error(self.path, self.evidence, run), "API_DISCOVERY_SOURCE_CARDS_INVALID")
        self.evidence["collections"]["patents"][-1]["payload"]["candidates"] = []
        run["status"] = "no_result"
        self.assertEqual(source_files_error(self.path, self.evidence, run), "API_DISCOVERY_SOURCE_CARDS_INVALID")

    def test_zero_result_needs_explicit_bounded_review_and_retains_scope(self):
        req = self.request()
        entries = next_work_entries(self.task, self.plan, self.evidence, self.candidates, self.ledger)
        self.assertTrue(any(e.get("query_id") == self.primary()["query_id"] and e["reason"] == "API_DISCOVERY_REVIEW_REQUIRED" for e in entries))
        req.update(role="review", outcome="stop_bounded_discovery", reason="Only the one-page discovery scope was reviewed; official coverage remains unresolved")
        record = append_followup(self.path, req)
        self.reload()
        self.assertEqual(record["discovery_scope"], self.primary()["discovery_scope"])
        entries = next_work_entries(self.task, self.plan, self.evidence, self.candidates, self.ledger)
        self.assertFalse(any(e.get("query_id") == self.primary()["query_id"] for e in entries))
        self.task["discovery_followups"][-1]["triage_digest"] = "0" * 64
        self.assertTrue(any(e.get("query_id") == self.primary()["query_id"] for e in next_work_entries(self.task, self.plan, self.evidence, self.candidates, self.ledger)))

    def test_failed_source_stop_requires_specific_blocker(self):
        run = self.source(status="failed")
        req = {"role": "review", "parent_query_id": self.primary()["query_id"], "source_run_id": run["run_id"],
            "reviewer": "unit-agent", "reason": "Provider failure was read; no executable alternative is currently available",
            "evidence_ids": [], "outcome": "blocked"}
        with self.assertRaisesRegex(ValueError, "BLOCKER_REQUIRED"):
            append_followup(self.path, req)
        req["blocker"] = "Primary timed out; no authorized fallback provider or supported browser adapter"
        self.assertEqual(append_followup(self.path, req)["outcome"], "blocked")

    def wrong_primary(self):
        row = make_row(self.task, "serpapi_google_patents", self.task["query_terms"][0], "US", "patent", self.primary()["requirement_ids"])
        self.plan["queries"].setdefault("serpapi_google_patents", []).append(row)
        # Simulate the pre-fix planner placing this intent only on the backup.
        self.plan["queries"]["serper_patents"] = [r for r in self.plan["queries"]["serper_patents"] if r["discovery_intent_id"] != row["discovery_intent_id"]]
        atomic_write_json(self.path / "search-plan.json", self.plan)
        return row

    def test_unsubmitted_primary_repair_is_append_only_and_same_intent(self):
        old = self.wrong_primary()
        before = deepcopy(old)
        req = {"role": "plan_repair", "parent_query_id": old["query_id"], "provider": "serper_patents", "term": self.task["query_terms"][0],
            "reason": "Repair a wrong-provider initial allocation", "reviewer": "unit-agent"}
        new = append_followup(self.path, req)
        self.reload()
        self.assertEqual(self.plan["queries"]["serpapi_google_patents"][0], before)
        self.assertEqual(new["discovery_intent_id"], old["discovery_intent_id"])
        self.assertEqual(scenario_dispatch_block_from_dir(self.path, "serpapi_google_patents", old)["code"], "SCENARIO_ACTION_CANCELLED")
        self.assertIsNone(scenario_dispatch_block_from_dir(self.path, "serper_patents", new))

    def test_primary_repair_never_rewrites_a_submitted_query(self):
        old = self.wrong_primary()
        self.source(old)
        with self.assertRaisesRegex(ValueError, "ALREADY_SUBMITTED"):
            append_followup(self.path, {"role": "plan_repair", "parent_query_id": old["query_id"], "provider": "serper_patents",
                "term": self.task["query_terms"][0], "reason": "Must not reset execution", "reviewer": "unit-agent"})

    def test_lens_scope_states_that_native_response_cannot_limit_cards(self):
        term = {**self.task["query_terms"][0], "discovery_channel": "image", "image_url": "https://example.com/product.jpg"}
        row = make_row(self.task, "serpapi_google_lens", term, "US", "copyright", [])
        self.assertEqual(row["discovery_scope"]["requested_candidates"], 10)
        self.assertFalse(row["discovery_scope"]["response_limit_enforceable"])
        self.assertEqual(row["discovery_scope"]["max_pages"], 1)
        self.assertNotIn("num", row)

    def test_lower_frozen_limits_control_browser_and_refinement(self):
        self.task["retrieval_policy"].update(max_refinement_rounds=1, browser_fallback_max_candidates=15, max_pages_per_query=2)
        self.regenerate()
        new = append_followup(self.path, self.request(role="browser_fallback", provider="uspto_patent_browser"))
        self.reload()
        self.assertEqual(new["discovery_scope"]["max_candidates"], 15)
        self.assertEqual(new["discovery_scope"]["max_pages"], 2)
        refined = append_followup(self.path, self.request(value="first rewrite"))
        self.reload()
        with self.assertRaisesRegex(ValueError, "ROUND_LIMIT"):
            append_followup(self.path, self.request(refined, value="second rewrite"))

    def test_legacy_marker_absent_retains_broad_original_planner(self):
        self.task.pop("retrieval_workflow_revision")
        self.task.pop("retrieval_policy")
        self.task["serper_free_enhancement"] = serper_free_enhancement(False)
        self.task["serpapi_free_enhancement"] = serpapi_free_enhancement(False)
        self.regenerate()
        self.assertIn("uspto_patent_browser", self.plan["queries"])
        self.assertNotIn("retrieval_workflow_revision", self.plan)
        assert_recall_planning_contract(self.task, self.plan)

    def asset_lookup(self, *, step="provenance", invalid=None, legacy=False):
        from decision_workflow import make_annotation
        from record_asset_provenance import asset_scope
        scenario_fixture.ScenarioPlanningTests.prepare_asset_candidate(self, "copyright")
        if legacy:
            self.task.pop("retrieval_workflow_revision", None)
            self.task.pop("retrieval_policy", None)
            self.task["serper_free_enhancement"] = serper_free_enhancement(False)
            self.task["serpapi_free_enhancement"] = serpapi_free_enhancement(False)
        self.regenerate()
        scope = asset_scope(self.task, "product_entry", "copyright")
        action = {"action_id": "LOOKUP-ASSET", "kind": "source_lookup", "purpose": "read_source_expression",
            "provider": "asset_provenance", "operation": "provenance_review", "max_attempts": 1,
            "params": {"q": "candidate-source:SYNTHETIC-ASSET", "candidate_id": self.candidate["candidate_id"],
                "asset_scope_sha256": scope["scope_sha256"]},
            "required_facts": ["protection_content"],
            "reading_scope": {"level": "protection_content", "investigation_step": step}}
        if invalid == "missing_scope":
            action["params"].pop("asset_scope_sha256")
        elif invalid == "stale_scope":
            action["params"]["asset_scope_sha256"] = "0" * 64
        elif invalid == "missing_step":
            action["reading_scope"].pop("investigation_step")
        elif invalid == "missing_candidate":
            action["params"].pop("candidate_id")
        self.ledger["annotations"] = [make_annotation(self.task, "copyright_assets", self.candidate, {
            "annotation_id": "D-LOOKUP-ASSET", "decision": "needs_info", "scenario_id": "product_entry",
            "reason": "The source expression needs a bounded original-source investigation", "reviewer": "offline-agent",
            "annotated_at": "2026-01-01T00:00:00Z", "evidence_refs": ["E1"], "reading_level": "result_record",
            "basis_summary": "Only the source discovery record has been read", "reopen_conditions": ["Original source evidence"],
            "missing_information": ["Original source expression and attribution"], "next_actions": [action]}, evidence=self.evidence)]
        self.save()
        from workflow_v24 import append_candidate_actions
        append_candidate_actions(self.path, self.task, self.candidates)
        self.plan = load_json(self.path / "search-plan.json")
        return action, scope, [row for row in self.plan["queries"].get("asset_provenance", [])
            if row.get("triage_action_id") == action["action_id"]]

    def test_needs_info_asset_lookup_reaches_existing_dispatch_and_recorder(self):
        from provider_utils import PLAN_META_KEYS
        from workflow_v24 import SCENARIO_META_KEYS
        from record_asset_provenance import validate_payload
        for step in ("provenance", "visual_comparison"):
            with self.subTest(step=step):
                action, scope, rows = self.asset_lookup(step=step)
                self.assertEqual(len(rows), 1)
                row = rows[0]
                self.assertEqual(row["search_dimension"], step)
                self.assertEqual(row["asset_scope_sha256"], scope["scope_sha256"])
                self.assertEqual({k: v for k, v in row.items() if k not in PLAN_META_KEYS and k not in SCENARIO_META_KEYS}, action["params"])
                self.assertIsNone(scenario_dispatch_block_from_dir(self.path, "asset_provenance", row))
                artifact = self.path / "synthetic-source.txt"
                artifact.write_text("Synthetic retained source for recorder identity validation only")
                payload = {"candidate_id": self.candidate["candidate_id"], "jurisdiction": "US", "right_type": "copyright",
                    "scenario_id": "product_entry", "asset_scope_sha256": scope["scope_sha256"], "reviewer": "offline-agent",
                    "ownership_or_source_reasoning": "Synthetic source investigation; no live claims", "source_url": "https://example.com/source",
                    "artifacts": [{"path": str(artifact), "sha256": sha256_file(artifact), "bytes": artifact.stat().st_size, "role": "source_text"}],
                    "coverage_attestation": {"inventory_complete": True, "asset_ids": ["shape"], "reviewed_asset_ids": ["shape"]},
                    "investigation_steps": [{"step": step, "status": "partial"}], "outstanding_actions": [], "unresolved": ["Synthetic fixture"]}
                self.assertEqual(validate_payload(self.path, payload, row, self.candidates, self.task)["candidate_id"], self.candidate["candidate_id"])

    def test_needs_info_asset_lookup_invalid_contract_is_explicit_gap_not_bad_row(self):
        for invalid, step in (("missing_scope", "provenance"), ("stale_scope", "provenance"),
                              ("missing_step", "provenance"), ("missing_candidate", "provenance"), (None, "identifier")):
            with self.subTest(invalid=invalid, step=step):
                _, _, rows = self.asset_lookup(step=step, invalid=invalid)
                self.assertEqual(rows, [])
                gaps = [gap for gap in self.plan["candidate_action_gaps"] if gap.get("action_id") == "LOOKUP-ASSET"]
                self.assertEqual(len(gaps), 1)
                self.assertEqual(gaps[0]["code"], "NEEDS_INFO_ACTION_UNSUPPORTED")
                self.assertIn("investigation_step", gaps[0]["reason"])

    def test_legacy_needs_info_asset_lookup_keeps_original_dimension(self):
        _, _, rows = self.asset_lookup(invalid="missing_scope", legacy=True)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["search_dimension"], "identifier")
        self.assertNotIn("asset_scope_sha256", rows[0])


if __name__ == "__main__":
    unittest.main()
