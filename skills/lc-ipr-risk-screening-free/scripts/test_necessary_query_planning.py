"""Offline query grammar and source-specific identity planning regressions."""
import copy
import json
from pathlib import Path
import unittest

from common import atomic_write_json, load_json, sha256_json
from record_browser_execution import compile_ppubs_boolean, compile_ppubs_query
from generate_search_plan import entry
import test_workflow_v24 as workflow_tests
from workflow_v24 import (boolean_tokens, brand_byline_disposition, generate_plan,
                         term_records, bind_scenario_action, work_view_from_dir,
                         build_coverage_requirements_v24, product_clue_inventory, product_identity_digest)


class NecessaryQueryPlanningTests(unittest.TestCase):
    def setUp(self):
        workflow_tests.RecallIntegrityTests.setUp(self)
        self.task["completion_policy_revision"] = "necessary-work-v1"
        self.save()

    tearDown = workflow_tests.RecallIntegrityTests.tearDown
    confirm = workflow_tests.RecallIntegrityTests.confirm

    def save(self):
        atomic_write_json(self.path / "task.json", self.task)

    def test_shared_boolean_fixture_is_identical_in_planner_and_receipts(self):
        fixture = Path(__file__).resolve().parents[1] / "tests/fixtures/ppubs-boolean-v2.json"
        for case in json.loads(fixture.read_text()):
            with self.subTest(query=case["q"]):
                if case.get("error"):
                    for compile_query in (compile_ppubs_boolean, boolean_tokens):
                        with self.assertRaisesRegex(ValueError, case["error"]):
                            compile_query(case["q"], "ppubs-boolean-v2")
                else:
                    rendered = compile_ppubs_boolean(case["q"], "ppubs-boolean-v2")
                    planned = " ".join(boolean_tokens(case["q"], "ppubs-boolean-v2"))
                    self.assertEqual(rendered, case["expected"])
                    self.assertEqual(compile_ppubs_boolean(planned, "ppubs-boolean-v2"), rendered)

    def test_reserved_word_becomes_agent_gap_and_other_source_continues(self):
        bad = {"kind": "structural_feature", "value": "layered ring with rectangular openings",
               "language": "en", "derived_from": "product.structure[0]", "strategy": "boolean"}
        self.task["query_terms"] = [bad]
        self.save()
        plan = generate_plan(self.path)
        self.assertFalse(any("with" in row["q"] for row in plan["queries"].get("uspto_patent_browser", [])))
        self.assertTrue(any('ta="with"' in row["q"] for row in plan["queries"]["epo_ops"]))
        gap = next(row for row in plan["planning_gaps"] if row["code"] == "UNSUPPORTED_QUERY_SEMANTICS")
        self.assertEqual(gap["provider"], "uspto_patent_browser")
        self.assertEqual(gap["query"], bad["value"])
        self.assertEqual(gap["assigned_to"], "agent")
        before = {row["query_id"]: sha256_json(row) for rows in plan["queries"].values() for row in rows}
        self.task["query_terms"][0]["value"] = "layered AND ring AND rectangular AND openings"
        self.save()
        repaired = generate_plan(self.path, expand=True)
        self.assertFalse(any(gap["code"] == "UNSUPPORTED_QUERY_SEMANTICS" for gap in repaired["planning_gaps"]))
        fixed = next(row for row in repaired["queries"]["uspto_patent_browser"] if "layered" in row["q"])
        self.assertEqual(fixed["query_compiler_revision"], "ppubs-boolean-v2")
        after = {row["query_id"]: sha256_json(row) for rows in repaired["queries"].values() for row in rows}
        self.assertTrue(all(after[key] == value for key, value in before.items()))

    def test_repair_rebinds_clues_and_clears_derived_work_without_rewriting_history(self):
        self.task.update(decision_workflow_revision="scenario-triage-v1",
                         workflow_correction_revision="workflow-correction-v1",
                         recall_planning_revision="identity-discovery-v1", specialty_workflow_revision="asset-scope-v1")
        self.task["coverage_requirements"] = build_coverage_requirements_v24(self.task["target_jurisdictions"],
            screening_revision=self.task["screening_revision"], specialty_workflow_revision="asset-scope-v1")
        self.task["query_terms"][0]["value"] = "layered ring with rectangular openings"
        def rebind(reason):
            self.task["product"]["analysis"] = {"status": "confirmed",
                "identity_sha256": product_identity_digest(self.task["product"], task=self.task),
                "clue_dispositions": [{"source_path": clue["source_path"], "source_sha256": clue["source_sha256"],
                    "disposition": "mapped", "reason": reason,
                    "query_term_sha256": [sha256_json(term) for term in self.task["query_terms"]
                        if term["derived_from"] == clue["source_path"]]} for clue in product_clue_inventory(self.task)]}
            self.save()
        rebind("Recorded visible structure")
        before = generate_plan(self.path)
        view = work_view_from_dir(self.path, source_capabilities={})
        self.assertTrue(any(row["kind"] == "plan_repair" and row["state"] == "ready"
            and row["reason"] == "UNSUPPORTED_QUERY_SEMANTICS" for row in view["entries"]))
        evidence_before = load_json(self.path / "evidence.json")
        self.task["query_terms"][0]["value"] = "layered AND ring AND rectangular AND openings"
        rebind("Removed the connective with because PPS reserves WITH; retained the visible feature terms")
        after = generate_plan(self.path, expand=True)
        view = work_view_from_dir(self.path, source_capabilities={})
        self.assertFalse(any(row["reason"] == "UNSUPPORTED_QUERY_SEMANTICS" for row in view["entries"]))
        self.assertEqual(evidence_before, load_json(self.path / "evidence.json"))
        after_rows = {row["query_id"]: row for rows in after["queries"].values() for row in rows}
        self.assertTrue(all(after_rows[row["query_id"]] == row for rows in before["queries"].values() for row in rows))

    def test_new_boolean_rows_only_and_historical_plan_stays_unchanged(self):
        self.task["query_terms"].append({"kind": "uspc", "value": "D8/1", "derived_from": "product.structure[1]"})
        self.save()
        plan = generate_plan(self.path)
        for row in plan["queries"]["uspto_patent_browser"]:
            if row["strategy"] == "boolean" and row["search_dimension"] != "classification":
                self.assertEqual(row["query_compiler_revision"], "ppubs-boolean-v2")
            else:
                self.assertNotIn("query_compiler_revision", row)
        self.assertEqual(plan["queries"], generate_plan(self.path, expand=True)["queries"])
        (self.path / "search-plan.json").unlink()
        self.task.pop("completion_policy_revision")
        self.task["query_terms"][0]["value"] = "ring with openings"
        self.save()
        historical = generate_plan(self.path)
        legacy = next(row for row in historical["queries"]["uspto_patent_browser"] if "with" in row["q"])
        self.assertNotIn("query_compiler_revision", legacy)
        self.assertEqual(legacy["q"], "ring AND with AND openings")
        self.assertEqual(historical["queries"], generate_plan(self.path, expand=True)["queries"])

    def test_lowercase_operators_are_semantic_and_quoted_words_are_preserved(self):
        source = '(ring or strap) and not "metal and plastic"'
        self.task["query_terms"][0]["value"] = source
        self.save()
        plan = generate_plan(self.path)
        row = next(row for row in plan["queries"]["uspto_patent_browser"] if row["search_dimension"] == "text"
                   and row["right_type"] == "patent")
        self.assertEqual(compile_ppubs_query(row, "structural_feature")["rendered_query"],
                         '(ring OR strap) AND NOT "metal and plastic"')
        self.assertEqual(self.task["query_terms"][0]["value"], source)

    def test_known_number_action_keeps_quoted_record_revision(self):
        self.task.update(decision_workflow_revision="scenario-triage-v1",
                         workflow_correction_revision="workflow-correction-v1")
        row = entry("uspto_patent_browser", "candidate_verification", "US",
                    {"q": "US11401089B2", "strategy": "record_number"}, required=False,
                    right_type="patent", requirement_ids=[], derived_from=["candidate:synthetic"], wave=2)
        row = bind_scenario_action(self.task, "uspto_patent_browser", row, purpose="official_verification")
        self.assertEqual(row["query_compiler_revision"], "ppubs-quoted-record-v1")
        self.assertEqual(compile_ppubs_query(row, "record_number")["rendered_query"], '"11401089".PN.')

    def test_generic_byline_excluded_but_observed_generic_mark_kept(self):
        self.task["product"].update(brand="Generic", brand_byline_raw="Brand: Generic", brand_placeholder=True)
        self.task["query_terms"].extend([
            {"kind": "brand", "value": "Brand: Generic", "language": "en", "derived_from": "product.brand"},
            {"kind": "brand", "value": "GENERIC", "language": "en", "derived_from": "product.mark_inventory[0]"},
        ])
        self.confirm()
        plan = generate_plan(self.path)
        trademarks = plan["queries"]["uspto_tmsearch_browser"]
        self.assertTrue(any(row["q"] == "GENERIC" and row["derived_from"] == ["product.mark_inventory[0]"] for row in trademarks))
        self.assertFalse(any("product.brand" in row["derived_from"] for row in trademarks))
        self.assertEqual(plan["term_dispositions"][0]["raw_value"], "Brand: Generic")
        self.assertEqual(plan["term_dispositions"][0]["code"], "AMAZON_BRAND_BYLINE_PLACEHOLDER")

    def test_capture_metadata_reaches_planner_and_missing_recapture_clears_it(self):
        from record_browser_product import merge_captured_product
        capture = {"title": "Synthetic product", "actual_asin": "B012345678",
            "variant": {"confirmed": True, "value": "fixture"}, "brand": "Generic",
            "brand_byline_raw": "Brand : Generic", "brand_placeholder": True}
        merge_captured_product(self.task, capture, [])
        self.assertEqual(self.task["product"]["raw_capture"]["brand_byline_raw"], "Brand : Generic")
        self.assertFalse(any(term["derived_from"] == "product.brand" for term in term_records(self.task)))
        capture.pop("brand_byline_raw")
        capture.pop("brand_placeholder")
        merge_captured_product(self.task, capture, [])
        self.assertNotIn("brand_placeholder", self.task["product"])
        self.assertTrue(any(term["derived_from"] == "product.brand" for term in term_records(self.task)))

    def test_placeholder_is_source_specific_and_historical_behavior_survives(self):
        for raw in ("Brand: Generic", "Brand : Generic", "Visit the Unbranded Store", "generic"):
            task = copy.deepcopy(self.task)
            task["product"].update(brand="Generic", brand_byline_raw=raw, brand_placeholder=True)
            self.assertIsNotNone(brand_byline_disposition(task))
            self.assertFalse(any(t["derived_from"] == "product.brand" for t in term_records(task)))
            task.pop("completion_policy_revision")
            self.assertTrue(any(t["derived_from"] == "product.brand" for t in term_records(task)))
        for fields in ({"brand": "Generic"}, {"brand": "Generic", "brand_placeholder": True},
                       {"brand": "Example", "brand_byline_raw": "Brand: Example", "brand_placeholder": True}):
            task = copy.deepcopy(self.task)
            task["product"].update(fields)
            self.assertIsNone(brand_byline_disposition(task))
            self.assertTrue(any(t["derived_from"] == "product.brand" for t in term_records(task)))


if __name__ == "__main__":
    unittest.main()
