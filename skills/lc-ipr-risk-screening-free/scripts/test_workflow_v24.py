"""New orchestration contracts; network and credential values are never used."""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common import atomic_write_json, canonical_coverage_requirements_match, load_json, sha256_json, RECALL_INTEGRITY_REVISION
from workflow_v24 import (generate_plan, append_candidate_actions, product_identity_digest,
                         product_analysis_readiness, planned_execution_gaps, boolean_tokens, build_coverage_requirements_v24,
                         validated_query_cancellation)
from runtime_v24 import execute_api_plan, preflight_credentials
from provider_plan_v24 import load_action
from provider_utils import PLAN_META_KEYS, coverage_route_policy


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        subprocess.run([sys.executable, str(Path(__file__).with_name("create_task.py")), "--url", "https://www.amazon.com/dp/B012345678", "--jurisdictions", "US,GB,FR,DE,IT,ES,JP", "--output-dir", str(self.path), "--enable-serper-free", "--enable-signa-free", "--enable-serpapi-free"], check=True, capture_output=True)
        self.task = load_json(self.path / "task.json")
        self.task.pop("workflow_correction_revision", None)  # Frozen pre-correction compatibility fixture.
        self.task.pop("decision_workflow_revision", None)  # Frozen pre-scenario contract.
        self.task.pop("specialty_workflow_revision", None)
        self.task.pop("screening_revision", None)  # Frozen pre-integrity 2.4 behavior.
        self.task.pop("recall_planning_revision", None)
        self.task["coverage_requirements"] = build_coverage_requirements_v24(self.task["target_jurisdictions"])
        self.task["state"] = "collecting"
        self.task["product"].update(title="folding phone stand", brand="Example", language="en", structure=["adjustable hinged support"])
        self.task["query_terms"] = [{"kind": "ipc", "value": "G06F3/039", "derived_from": "product.structure[0]"}, {"kind": "translation", "value": "support articulé", "language": "fr", "derived_from": "product.structure[0]"}]
        atomic_write_json(self.path / "task.json", self.task)

    def tearDown(self):
        self.temp.cleanup()

    def test_seven_country_plan_keeps_uk_ep_and_real_languages(self):
        plan = generate_plan(self.path)
        self.assertTrue(canonical_coverage_requirements_match(self.task))
        self.assertEqual(set(self.task["target_jurisdictions"]), {"US", "GB", "EU", "FR", "DE", "IT", "ES", "JP"})
        gb = [r for r in plan["queries"]["epo_ops"] if r["jurisdiction"] == "GB" and r["right_type"] == "patent"]
        self.assertTrue(gb)
        self.assertTrue(all("EP" in r["publication_scope"] for r in gb))
        self.assertTrue(any(r["search_language"] == "fr" for r in plan["queries"]["inpi_api"]))
        self.assertTrue(all(r["q"].startswith("[") for r in plan["queries"]["inpi_api"]))
        self.assertFalse(any(p.startswith("wipo") for p in plan["queries"]))
        self.assertTrue(all(r["routes"] for r in self.task["coverage_requirements"]))

    def test_us_plan_rejects_cjk_text_mislabeled_as_english(self):
        self.task["product"].update(language="en", structure=[
            {"description": "适配多种慢炖锅的通用锅盖固定带", "language": "en"},
            {"description": "silicone lid securing strap with oval adjustment holes", "language": "en"},
        ])
        self.task["query_terms"] = []
        atomic_write_json(self.path / "task.json", self.task)
        plan = generate_plan(self.path)
        cjk = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
        self.assertEqual(
            next(term["language"] for term in plan["terms"] if cjk.search(term["value"])),
            "zh",
        )
        us_text = [
            row for rows in plan["queries"].values() for row in rows
            if row.get("jurisdiction") == "US" and row.get("search_dimension") == "text"
        ]
        self.assertTrue(us_text)
        self.assertTrue(all(row.get("search_language") == "en" and not cjk.search(row["q"]) for row in us_text))

    def test_expansion_is_append_only_and_paginates_actual_bound_result(self):
        plan = generate_plan(self.path)
        before = {r["query_id"]: sha256_json(r) for rows in plan["queries"].values() for r in rows}
        first = plan["queries"]["epo_ops"][0]
        evidence = load_json(self.path / "evidence.json")
        evidence["source_runs"].append({"provider": "epo_ops", "query_id": first["query_id"], "plan_entry_sha256": sha256_json(first), "status": "success", "metadata": {"search_coverage": {"total_hits": 60, "retrieved_hits": 25, "schema_valid": True}}})
        atomic_write_json(self.path / "evidence.json", evidence)
        expanded = generate_plan(self.path, expand=True)
        after = {r["query_id"]: sha256_json(r) for rows in expanded["queries"].values() for r in rows}
        self.assertTrue(all(after[q] == digest for q, digest in before.items()))
        self.assertTrue(any(r.get("range") == "26-50" and r["q"] == first["q"] for r in expanded["queries"]["epo_ops"]))
        self.assertEqual(expanded["queries"], generate_plan(self.path, expand=True)["queries"])

    def test_missing_api_accounts_continue_and_record_gaps_never_zero(self):
        generate_plan(self.path)
        with patch("runtime_v24.credential", return_value=""), patch("runtime_v24.subprocess.run") as network:
            output = execute_api_plan(self.path)
        network.assert_not_called()
        self.assertTrue(output["results"])
        self.assertTrue(all(r["status"] == "access_limited" for r in output["results"]))
        self.assertTrue(all(r["error_code"] == "OPTIONAL_CREDENTIALS_MISSING" for r in output["results"]))
        self.assertTrue(all(r["manual_business_work"] is False for r in output["agent_browser_queue"]))

    def test_optional_accounts_do_not_fail_startup(self):
        self.task["state"] = "pending"
        atomic_write_json(self.path / "task.json", self.task)
        with patch("auth_gate.require_auth"), patch("runtime_v24.credential", return_value=""):
            self.assertEqual(preflight_credentials(self.path), "awaiting_browser")
        caps = load_json(self.path / "source-capabilities.json")["sources"]
        self.assertEqual(next(c["state"] for c in caps if c["provider"] == "epo_ops"), "unavailable")
        self.assertEqual(next(c["state"] for c in caps if c["provider"] == "epo_publication_server"), "automatic")

    def test_ep_document_and_country_effect_actions_are_separate(self):
        generate_plan(self.path)
        candidates = {"patents": [{"candidate_id": "CAND-EP", "right_type": "patent", "jurisdiction": "EP", "publication_number": "EP1004359B1", "material": True}], "trademarks": []}
        append_candidate_actions(self.path, self.task, candidates)
        plan = load_json(self.path / "search-plan.json")
        eps = plan["queries"]["epo_publication_server"][0]
        self.assertEqual(eps["jurisdiction"], "EP")
        self.assertEqual(eps["requirement_ids"], [])
        load_action(self.path, "epo_publication_server", eps["query_id"], {"document_retrieval"})
        self.assertEqual(coverage_route_policy(self.task, "epo_publication_server", "document_retrieval", jurisdiction="EP", right_type="patent"), (True, False))
        countries = {r["jurisdiction"] for r in plan["queries"]["official_registry_browser"] if r["operation"] == "candidate_verification"}
        self.assertEqual(countries, {"GB", "FR", "DE", "IT", "ES"})

    def test_lens_uses_same_total_free_budget(self):
        self.task["images"] = [{"source_url": "https://m.media-amazon.com/images/I/example.jpg", "sha256": "fixture"}]
        atomic_write_json(self.path / "task.json", self.task)
        plan = generate_plan(self.path)
        self.assertEqual(len(plan["queries"]["serpapi_google_lens"]), 1)
        self.assertLessEqual(sum(len(v) for k, v in plan["queries"].items() if k.startswith("serpapi")), 3)
        row = plan["queries"]["serpapi_google_lens"][0]
        load_action(self.path, "serpapi_google_lens", row["query_id"], {"image_search"})

    def test_copyright_candidate_provenance_is_reachable_without_registry_number(self):
        generate_plan(self.path)
        candidates = {"copyright_assets": [{"candidate_id": "COPY-1", "right_type": "copyright", "material": True}]}
        append_candidate_actions(self.path, self.task, candidates)
        plan = load_json(self.path / "search-plan.json")
        rows = [r for r in plan["queries"]["asset_provenance"] if r.get("candidate_id") == "COPY-1"]
        self.assertEqual({r["jurisdiction"] for r in rows}, set(self.task["target_jurisdictions"]))
        self.assertTrue(all("registration_number" not in r for r in rows))

    def test_family_grouping_preserves_actual_member_numbers(self):
        from merge_candidates import add_family_groups, _candidate_document_for_jurisdiction
        candidates = [{"family_id": "123", "publication_number": "WO2020012345A1", "normalization_key": "patent:wo-key", "jurisdiction": "WO", "family_members": ["EP1004359B1", "US1234567B1"]}]
        add_family_groups(candidates, preserve_identifiers=True)
        self.assertEqual(_candidate_document_for_jurisdiction(candidates[0], "EU"), "EP1004359B1")
        self.assertIn("patent:wo-key", candidates[0]["family_candidate_keys"])
        self.assertNotIn("patent:wo-key", candidates[0]["family_members"])

    def test_duplicate_ids_fail_before_execution(self):
        plan = generate_plan(self.path)
        plan["queries"]["epo_ops"].append(dict(plan["queries"]["epo_ops"][0]))
        atomic_write_json(self.path / "search-plan.json", plan)
        with patch("runtime_v24.credential", return_value=""), self.assertRaisesRegex(ValueError, "Duplicate query"):
            execute_api_plan(self.path)

    def test_cross_country_family_members_have_independent_candidate_identity(self):
        from merge_candidates import expand_family_candidates
        patents = [{"candidate_id": "CAND-US", "jurisdiction": "US", "right_type": "patent", "publication_number": "US1234567B1", "family_id": "family-1", "family_members": ["EP1004359B1", "JP2020123456A"], "material": True, "claims": ["US claim"], "official_verification": {"status": "verified"}}]
        expand_family_candidates(patents)
        self.assertEqual({c["jurisdiction"] for c in patents}, {"US", "EP", "JP"})
        for candidate in patents[1:]:
            self.assertNotIn("claims", candidate)
            self.assertFalse(candidate["material"])
            self.assertEqual(candidate["official_verification"]["status"], "not_checked")
            candidate["material"] = True  # Agent decisions after separate review.
        generate_plan(self.path)
        append_candidate_actions(self.path, self.task, {"patents": patents})
        queries = load_json(self.path / "search-plan.json")["queries"]
        self.assertTrue(any(r["q"] == "JP2020123456A" for r in queries.get("jpo_api", [])))
        self.assertTrue(queries.get("epo_publication_server"))
        self.assertTrue(any(r["jurisdiction"] == "GB" and r["operation"] == "candidate_verification" for r in queries["official_registry_browser"]))

    def test_euipo_locarno_and_late_translation_are_planned(self):
        first = generate_plan(self.path)
        self.task["query_terms"].extend([{"kind": "locarno", "value": "12-08", "derived_from": "product.structure[0]"}, {"kind": "translation", "value": "supporto pieghevole", "language": "it", "derived_from": "product.structure[0]"}])
        atomic_write_json(self.path / "task.json", self.task)
        plan = generate_plan(self.path, expand=True)
        self.assertTrue(any(r.get("query") == "locarnoClasses==12.08" and r["search_dimension"] == "classification" for r in plan["queries"]["euipo_design"]))
        self.assertTrue(any(r.get("search_language") == "it" for r in plan["queries"]["epo_ops"]))


class RecallIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        subprocess.run([sys.executable, str(Path(__file__).with_name("create_task.py")), "--url", "https://www.amazon.com/dp/B012345678", "--jurisdictions", "US", "--output-dir", str(self.path)], check=True, capture_output=True)
        self.task = load_json(self.path / "task.json")
        self.task.pop("workflow_correction_revision", None)  # Frozen recall-integrity compatibility fixture.
        self.task.pop("decision_workflow_revision", None)  # Frozen recall-integrity contract.
        self.task.pop("specialty_workflow_revision", None)
        self.task["coverage_requirements"] = build_coverage_requirements_v24(self.task["target_jurisdictions"], screening_revision=self.task.get("screening_revision"))
        self.task.pop("recall_planning_revision", None)  # Original integrity contract; identity handoff has separate tests.
        self.task.update(screening_revision=RECALL_INTEGRITY_REVISION, state="collecting")
        self.task["product"].update(actual_asin="B012345678", variant={"confirmed": True, "value": "black"},
                                    title="Synthetic folding stand marketing headline", brand="Example", manufacturer="NotAnAssignee",
                                    category="Home > Accessories > Supports", bullets=["The best patented folding support for travel"],
                                    specifications={}, language="en", media_identity=["fixture-media-hash"],
                                    structure=["hinged support", "flat folded outline"])
        self.task["query_terms"] = [
            {"kind": "structural_feature", "value": "hinged support", "language": "en", "derived_from": "product.structure[0]"},
            {"kind": "design", "value": "(stand OR support) AND (folding OR hinged)", "language": "en", "strategy": "boolean", "derived_from": "product.structure[1]"},
            {"kind": "inventor", "value": "Synthetic Inventor", "derived_from": "evidence:inventor-bio"},
        ]
        self.confirm()

    def tearDown(self):
        self.temp.cleanup()

    def confirm(self):
        self.task["product"]["analysis"] = {"status": "confirmed", "identity_sha256": product_identity_digest(self.task["product"])}
        atomic_write_json(self.path / "task.json", self.task)

    def test_missing_analysis_blocks_plan_not_empty_recall(self):
        self.task["product"]["structure"] = []
        self.task["query_terms"] = []
        atomic_write_json(self.path / "task.json", self.task)
        with self.assertRaisesRegex(ValueError, "PRODUCT_ANALYSIS_NOT_READY"):
            generate_plan(self.path)
        self.assertFalse((self.path / "search-plan.json").exists())

    def test_strict_queries_are_decomposed_and_design_route_is_executable(self):
        plan = generate_plan(self.path)
        us_rows = plan["queries"]["uspto_patent_browser"]
        design = [r for r in us_rows if r["right_type"] == "design"]
        self.assertTrue(design)
        self.assertTrue(all(r["operation"] == "design_recall" for r in design))
        self.assertTrue(all(r["strategy"] in {"boolean", "phrase"} for r in us_rows))
        self.assertTrue(any(r["q"] == "hinged AND support" for r in us_rows))
        self.assertTrue(any("( stand OR support )" in r["q"] for r in design))
        for raw in (self.task["product"]["title"], self.task["product"]["category"], self.task["product"]["manufacturer"], self.task["product"]["bullets"][0]):
            self.assertFalse(any(raw == term["value"] for term in plan["terms"]))
        self.assertTrue(any('ta="hinged" AND ta="support"'.lower() in r["q"].lower() for r in plan["queries"]["epo_ops"]))

    def test_mismatched_route_is_internal_error(self):
        for requirement in self.task["coverage_requirements"]:
            if requirement["right_type"] == "design":
                for route in requirement["routes"]:
                    if route["provider"] == "uspto_patent_browser" and route["operation"] == "design_recall":
                        route["operation"] = "patent_recall"
        atomic_write_json(self.path / "task.json", self.task)
        with self.assertRaisesRegex(ValueError, "INTERNAL_ROUTE_CONTRACT_ERROR"):
            generate_plan(self.path)

    def test_inventor_default_is_order_independent_but_explicit_phrase_is_preserved(self):
        from record_browser_execution import compile_ppubs_query
        from workflow_v24 import term_records, _api_params
        for name in ("Synthetic Inventor", "Synthetic Middle Inventor"):
            for explicit in (None, "phrase"):
                with self.subTest(name=name, explicit=explicit):
                    term = {"kind": "inventor", "value": name, "derived_from": "evidence:inventor-bio"}
                    if explicit:
                        term["strategy"] = explicit
                    task = dict(self.task, query_terms=[term])
                    normalized = next(t for t in term_records(task) if t["kind"] == "inventor")
                    self.assertEqual(normalized["strategy"], explicit or "boolean")
                    params = _api_params("uspto_patent_browser", normalized, "US", "patent")
                    compiled = compile_ppubs_query(params, "inventor")["rendered_query"]
                    expected = f'("{name}").INV.' if explicit else f'({" AND ".join(name.split())}).INV.'
                    self.assertEqual(compiled, expected)
                    ops = _api_params("epo_ops", normalized, "US", "patent")["q"]
                    expression = f'in="{name}"' if explicit else " and ".join(f'in="{word}"' for word in name.split())
                    self.assertIn(expression, ops)
        task = dict(self.task, query_terms=[{"kind": kind, "value": "Synthetic Entity", "derived_from": "evidence:entity", "language": "en"}
                                           for kind in ("owner", "applicant", "brand", "ocr")])
        self.assertTrue(all(term["strategy"] == "phrase" for term in term_records(task)))
        historical = dict(self.task, screening_revision=None)
        self.assertTrue(all("strategy" not in term for term in term_records(historical)))

    def test_candidate_inventor_expansion_uses_boolean_without_changing_legacy(self):
        from record_browser_execution import compile_ppubs_query
        generate_plan(self.path)
        atomic_write_json(self.path / "normalized-candidates.json", {"patents": [
            {"candidate_id": "CAND-SYNTHETIC", "material": True, "inventors": ["Synthetic Middle Inventor"], "owner": "Synthetic Owner"}]})
        expanded = generate_plan(self.path, expand=True)
        row = next(r for r in expanded["queries"]["uspto_patent_browser"]
                   if r["derived_from"] == ["candidate:CAND-SYNTHETIC:inventors"] and r["right_type"] == "patent")
        self.assertEqual(row["strategy"], "boolean")
        self.assertEqual(compile_ppubs_query(row, "inventor")["rendered_query"], "(Synthetic AND Middle AND Inventor).INV.")
        owner = next(r for r in expanded["queries"]["uspto_patent_browser"]
                     if r["derived_from"] == ["candidate:CAND-SYNTHETIC:owner"])
        self.assertEqual(owner["strategy"], "phrase")
        self.task.pop("screening_revision")
        self.task["product"]["manufacturer"] = ""
        self.task["query_terms"] = [term for term in self.task["query_terms"] if term["kind"] != "inventor"]
        self.task["coverage_requirements"] = build_coverage_requirements_v24(self.task["target_jurisdictions"])
        atomic_write_json(self.path / "task.json", self.task)
        # A separate legacy plan is built in the same isolated fixture directory;
        # no real task is migrated or its executed rows rewritten.
        (self.path / "search-plan.json").unlink()
        legacy = generate_plan(self.path, expand=True)
        rows = [r for r in legacy["queries"]["uspto_patent_browser"]
                if r["derived_from"] == ["candidate:CAND-SYNTHETIC:inventors"]]
        self.assertTrue(rows)
        self.assertTrue(all("strategy" not in r for r in rows))

    def test_long_phrase_and_provider_syntax_are_rejected(self):
        self.task["query_terms"][0].update(value="this entire long marketing sentence should never become a literal query", strategy="phrase")
        atomic_write_json(self.path / "task.json", self.task)
        with self.assertRaisesRegex(ValueError, "short unquoted phrase"):
            generate_plan(self.path)
        for value in ("lid.PN.", "(lid OR)", "lid AND (cover", "lid OR OR cover"):
            with self.assertRaises(ValueError):
                boolean_tokens(value)

    def test_patent_claim_followup_is_work_not_an_empty_search(self):
        readiness = product_analysis_readiness(self.task)
        self.assertTrue(readiness["ready"])
        self.assertTrue(readiness["patent_claim_followup"]["required"])
        self.assertIn("PATENT_CLAIM_FOLLOWUP_MISSING", [g["code"] for g in readiness["gaps"]])
        self.task["product"]["patent_claim_followup"] = {"status": "completed"}
        self.assertEqual(product_analysis_readiness(self.task)["patent_claim_followup"]["status"], "pending")
        self.task["product"]["patent_claim_followup"].update(evidence_ids=["EV-actual-source"], findings="Identified the named inventor in sourced material")
        self.assertEqual(product_analysis_readiness(self.task)["patent_claim_followup"]["status"], "completed")

    def test_capture_keeps_confirmed_analysis_and_identity_change_invalidates_it(self):
        from copy import deepcopy
        from record_browser_product import merge_captured_product
        captured = deepcopy(self.task["product"])
        captured.pop("structure")
        before_terms = deepcopy(self.task["query_terms"])
        merge_captured_product(self.task, captured, ["fixture-media-hash"])
        self.assertEqual(self.task["query_terms"], before_terms)
        self.assertEqual(self.task["product"]["structure"], ["hinged support", "flat folded outline"])
        self.assertEqual(self.task["product"]["analysis"]["status"], "confirmed")
        captured["variant"]["value"] = "different-form"
        merge_captured_product(self.task, captured, ["new-media-hash"])
        self.assertEqual(self.task["product"]["analysis"]["status"], "stale")
        self.assertFalse(product_analysis_readiness(self.task)["ready"])
        self.assertEqual(self.task["query_terms"], before_terms)

    def test_new_wave_requires_execution_and_hash_bound_complete_alternative(self):
        plan = generate_plan(self.path)
        row = next(r for r in plan["queries"]["uspto_patent_browser"] if r["right_type"] == "design")
        evidence = {"source_runs": []}
        self.assertIn(row["query_id"], [g["query_id"] for g in planned_execution_gaps(self.task, plan, evidence)])
        evidence["source_runs"].append({"provider": "uspto_patent_browser", "query_id": row["query_id"],
                                        "plan_entry_sha256": sha256_json(row), "status": "no_result",
                                        "metadata": {"search_coverage": {"schema_valid": True, "truncated": False}}})
        self.assertNotIn(row["query_id"], [g["query_id"] for g in planned_execution_gaps(self.task, plan, evidence)])
        evidence["source_runs"][0]["metadata"]["search_coverage"]["truncated"] = True
        self.assertIn("SEARCH_RESULT_TRUNCATED", [g["code"] for g in planned_execution_gaps(self.task, plan, evidence)])
        evidence["source_runs"][0]["plan_entry_sha256"] = "wrong"
        gap = next(g for g in planned_execution_gaps(self.task, plan, evidence) if g["query_id"] == row["query_id"])
        self.assertEqual(gap["code"], "PLANNED_QUERY_NOT_EXECUTED")
        plan["execution_dispositions"] = [{"query_id": row["query_id"], "plan_entry_sha256": sha256_json(row), "status": "cancelled", "reason": "Superseded by a separately recorded narrower query; coverage remains audited"}]
        self.assertNotIn(row["query_id"], [g["query_id"] for g in planned_execution_gaps(self.task, plan, evidence)])

    def test_expansion_rows_are_pending_and_keep_initial_hashes(self):
        first = generate_plan(self.path)
        hashes = {r["query_id"]: sha256_json(r) for group in first["queries"].values() for r in group}
        self.task["query_terms"].append({"kind": "design", "value": "flat folded outline", "language": "en", "derived_from": "product.structure[1]"})
        atomic_write_json(self.path / "task.json", self.task)
        expanded = generate_plan(self.path, expand=True)
        after = {r["query_id"]: sha256_json(r) for group in expanded["queries"].values() for r in group}
        new_ids = set(after) - set(hashes)
        self.assertTrue(new_ids)
        self.assertTrue(all(after[key] == digest for key, digest in hashes.items()))
        gaps = planned_execution_gaps(self.task, expanded, {"source_runs": []})
        self.assertTrue(new_ids.issubset({gap["query_id"] for gap in gaps}))

    def test_cancellation_validation_is_strict_and_malformed_records_cannot_skip(self):
        plan = generate_plan(self.path)
        row = plan["queries"]["uspto_patent_browser"][0]
        cancellation = {"query_id": row["query_id"], "plan_entry_sha256": sha256_json(row),
                        "status": "cancelled", "reason": "Replaced by a narrower recorded query"}
        malformed = [None, True, "cancelled", {}, [None, 5, "cancelled"],
                     [dict(cancellation, query_id="different")], [dict(cancellation, plan_entry_sha256="stale")],
                     [dict(cancellation, status="pending")], [dict(cancellation, reason=" ")],
                     [dict(cancellation, reason={"text": "not a reason string"})]]
        for dispositions in malformed:
            with self.subTest(dispositions=dispositions):
                plan["execution_dispositions"] = dispositions
                self.assertIsNone(validated_query_cancellation(self.task, plan, row))
                self.assertIn(row["query_id"], {g["query_id"] for g in planned_execution_gaps(self.task, plan, {"source_runs": []})})
        plan["execution_dispositions"] = [None, cancellation]
        self.assertEqual(validated_query_cancellation(self.task, plan, row), cancellation)
        self.assertIsNone(validated_query_cancellation(dict(self.task, screening_revision=None), plan, row))
        self.assertIsNone(validated_query_cancellation(self.task, dict(plan, screening_revision=None), row))
        self.assertIsNone(validated_query_cancellation(self.task, plan, dict(row, q="changed query")))

    def test_expansion_preserves_cancellation_audit_and_skips_cancelled_pagination(self):
        first = generate_plan(self.path)
        row = first["queries"]["epo_ops"][0]
        cancellation = {"query_id": row["query_id"], "plan_entry_sha256": sha256_json(row),
                        "status": "cancelled", "reason": "Broad query superseded by a feature-group query",
                        "recorded_at": "2026-09-06T00:00:00Z"}
        first["execution_dispositions"] = [cancellation]
        atomic_write_json(self.path / "search-plan.json", first)
        hashes = {r["query_id"]: sha256_json(r) for group in first["queries"].values() for r in group}
        evidence = load_json(self.path / "evidence.json")
        evidence["source_runs"] = [{"provider": "epo_ops", "query_id": row["query_id"],
            "plan_entry_sha256": sha256_json(row), "status": "success",
            "metadata": {"search_coverage": {"schema_valid": True, "truncated": True, "total_hits": 40, "retrieved_hits": 25}}}]
        atomic_write_json(self.path / "evidence.json", evidence)
        self.task["query_terms"].append({"kind": "design", "value": "flat folded outline",
                                       "language": "en", "derived_from": "product.structure[1]"})
        atomic_write_json(self.path / "task.json", self.task)
        expanded = generate_plan(self.path, expand=True)
        self.assertEqual(expanded["execution_dispositions"], first["execution_dispositions"])
        after = {r["query_id"]: sha256_json(r) for group in expanded["queries"].values() for r in group}
        self.assertTrue(set(after) - set(hashes))
        self.assertTrue(all(after[key] == digest for key, digest in hashes.items()))
        self.assertFalse(any(r.get("range") == "26-50" and r["q"] == row["q"] for r in expanded["queries"]["epo_ops"]))
        self.assertNotIn(row["query_id"], {g["query_id"] for g in planned_execution_gaps(self.task, expanded, evidence)})

    def test_executed_pagination_completes_first_page_truncation(self):
        plan = generate_plan(self.path)
        first = plan["queries"]["epo_ops"][0]
        evidence = load_json(self.path / "evidence.json")
        evidence["source_runs"] = [{"provider": "epo_ops", "query_id": first["query_id"], "plan_entry_sha256": sha256_json(first), "status": "success",
                                   "metadata": {"search_coverage": {"schema_valid": True, "truncated": True, "total_hits": 40, "retrieved_hits": 25}}}]
        atomic_write_json(self.path / "evidence.json", evidence)
        plan = generate_plan(self.path, expand=True)
        second = next(r for r in plan["queries"]["epo_ops"] if r["q"] == first["q"] and r.get("range") == "26-50")
        evidence["source_runs"].append({"provider": "epo_ops", "query_id": second["query_id"], "plan_entry_sha256": sha256_json(second), "status": "success",
                                        "metadata": {"search_coverage": {"schema_valid": True, "truncated": False, "total_hits": 40, "retrieved_hits": 15}}})
        gaps = planned_execution_gaps(self.task, plan, evidence)
        self.assertNotIn(first["query_id"], {gap["query_id"] for gap in gaps})
        self.assertNotIn(second["query_id"], {gap["query_id"] for gap in gaps})

    def test_identity_ignores_rank_but_not_physical_dimensions(self):
        product = self.task["product"]
        product["specifications"] = {"Best Sellers Rank": "100", "Customer Reviews": "4.2", "Dimensions": "10 x 5"}
        before = product_identity_digest(product)
        product["specifications"].update({"Best Sellers Rank": "55", "Customer Reviews": "4.5"})
        self.assertEqual(before, product_identity_digest(product))
        product["specifications"]["Dimensions"] = "15 x 8"
        self.assertNotEqual(before, product_identity_digest(product))

    def test_pps_planning_uses_the_shared_compiler_contract(self):
        from workflow_v24 import _api_params
        cases = load_json(Path(__file__).parent.parent / "fixtures" / "ppubs-query-contract.json")["cases"]
        for case in cases:
            if case["strategy"] in {None, "record_number"} or re.search(r"[\u3400-\u9fff]", case["q"]):
                continue  # Readiness/language and candidate-action boundaries are tested separately.
            with self.subTest(query=case["q"]):
                params = _api_params("uspto_patent_browser", {"value": case["q"], "kind": case["field"], "strategy": case["strategy"], "language": "en"}, "US", case["right_type"])
                self.assertEqual(params is None, bool(case.get("error")))

    def test_ops_never_disguises_unsupported_classification_as_text(self):
        from workflow_v24 import _api_params
        for kind, value in (("uspc", "D7/391"), ("locarno", "07-02")):
            with self.subTest(kind=kind):
                self.assertIsNone(_api_params("epo_ops", {"kind": kind, "value": value,
                    "strategy": "boolean", "derived_from": "evidence:classification"}, "US", "design"))
        params = _api_params("epo_ops", {"kind": "cpc", "value": "A47J36/12",
            "strategy": "boolean", "derived_from": "evidence:classification"}, "US", "patent")
        self.assertIn('cpc="A47J36/12"', params["q"])
        self.assertNotIn('ta=', params["q"])


if __name__ == "__main__":
    unittest.main()
